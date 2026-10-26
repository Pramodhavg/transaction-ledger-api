import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BalanceLimitExceededError, DuplicateTransferError, SameAccountTransferError
from app.core.money import MAX_BALANCE
from app.db.errors import constraint_name, is_numeric_overflow
from app.models import Account, Transfer
from app.models.transfer import UQ_TRANSFER_REFERENCE
from app.schemas.transaction import TRANSFER_REFERENCE_PREFIX, TransactionType
from app.schemas.transfer import TransferCreate, TransferResponse
from app.services import account_service
from app.services.transaction_service import post_entry


def create_transfer(db: Session, data: TransferCreate) -> tuple[Transfer, Account, Account]:
    """Moves money between two accounts: a debit on the source and a credit on the destination.

    Both ledger entries, the transfer record and both balances are written in ONE database
    transaction, so a transfer is never partial: any failure rolls everything back.
    """
    if data.from_account_id == data.to_account_id:
        raise SameAccountTransferError(data.from_account_id)

    try:
        with db.begin():
            # Lock both accounts in a fixed global order (sorted by id). Without it, A->B and
            # B->A running at the same time could each lock one account and wait forever for
            # the other (a deadlock). With one order, a waiting cycle cannot form.
            locked = {
                account_id: account_service.lock_account(db, account_id)
                for account_id in sorted([data.from_account_id, data.to_account_id])
            }
            source, destination = locked[data.from_account_id], locked[data.to_account_id]

            existing = _find_by_reference(db, source.id, data.reference_id)
            if existing is not None:
                raise DuplicateTransferError(data.reference_id, _snapshot(existing))

            transfer = Transfer(
                id=uuid.uuid4(),
                from_account_id=source.id,
                to_account_id=destination.id,
                amount=data.amount,
                reference_id=data.reference_id,
                description=data.description,
            )
            db.add(transfer)
            db.flush()  # the transfer row must exist before the legs reference it

            # Leg references use the reserved "transfer:" prefix, so they can never collide
            # with a client's own reference_id on either account.
            post_entry(
                db,
                source,
                TransactionType.DEBIT,
                data.amount,
                f"{TRANSFER_REFERENCE_PREFIX}{transfer.id}:debit",
                data.description or f"Transfer to {destination.id}",
                transfer_id=transfer.id,
            )
            post_entry(
                db,
                destination,
                TransactionType.CREDIT,
                data.amount,
                f"{TRANSFER_REFERENCE_PREFIX}{transfer.id}:credit",
                data.description or f"Transfer from {source.id}",
                transfer_id=transfer.id,
            )
            return transfer, source, destination
    except IntegrityError as exc:
        # Backstop for the UNIQUE (from_account_id, reference_id) constraint.
        if constraint_name(exc) != UQ_TRANSFER_REFERENCE:
            raise
        existing = _find_by_reference(db, data.from_account_id, data.reference_id)
        if existing is None:
            raise
        raise DuplicateTransferError(data.reference_id, _snapshot(existing)) from exc
    except DataError as exc:
        # Backstop: the destination balance is too large for NUMERIC(18, 2).
        if not is_numeric_overflow(exc):
            raise
        raise BalanceLimitExceededError(data.to_account_id, MAX_BALANCE) from exc


def _find_by_reference(db: Session, from_account_id: uuid.UUID, reference_id: str) -> Transfer | None:
    stmt = select(Transfer).where(
        Transfer.from_account_id == from_account_id, Transfer.reference_id == reference_id
    )
    return db.scalars(stmt).one_or_none()


def _snapshot(transfer: Transfer) -> dict[str, Any]:
    # Serialised while still inside the DB transaction: a rollback expires ORM objects.
    return TransferResponse.model_validate(transfer).model_dump(mode="json")
