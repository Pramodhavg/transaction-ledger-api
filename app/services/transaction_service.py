from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import (
    BalanceLimitExceededError,
    DuplicateTransactionError,
    InsufficientBalanceError,
)
from app.core.money import MAX_BALANCE
from app.db.errors import constraint_name, is_numeric_overflow
from app.models import Account, Transaction
from app.models.transaction import UQ_TRANSACTION_REFERENCE
from app.schemas.transaction import TransactionCreate, TransactionResponse, TransactionType
from app.services import account_service


def create_transaction(db: Session, account_id: UUID, data: TransactionCreate) -> Transaction:
    """Applies a credit or debit to an account.

    Everything runs in ONE database transaction: the ledger row and the new balance are
    committed together, or (on any error) neither is.
    """
    try:
        with db.begin():
            # 1. Lock the account row. Concurrent requests for this account queue up here.
            account = account_service.lock_account(db, account_id)

            # 2. Idempotency: the same reference on this account is a retry, not a new entry.
            existing = _find_by_reference(db, account_id, data.reference_id)
            if existing is not None:
                raise DuplicateTransactionError(data.reference_id, _snapshot(existing))

            # 3 + 4. Check the balance, write the entry, move the balance.
            return post_entry(
                db, account, data.type, data.amount, data.reference_id, data.description
            )
    except IntegrityError as exc:
        # Backstop: the UNIQUE (account_id, reference_id) constraint caught a duplicate that
        # slipped past step 2. The lock makes this practically impossible, but the database
        # guarantees correctness even if the code above were wrong.
        if constraint_name(exc) != UQ_TRANSACTION_REFERENCE:
            raise
        existing = _find_by_reference(db, account_id, data.reference_id)
        if existing is None:
            raise
        raise DuplicateTransactionError(data.reference_id, _snapshot(existing)) from exc
    except DataError as exc:
        # Backstop: Postgres refused a balance too large for NUMERIC(18, 2).
        if not is_numeric_overflow(exc):
            raise
        raise BalanceLimitExceededError(account_id, MAX_BALANCE) from exc


def post_entry(
    db: Session,
    account: Account,
    type_: TransactionType,
    amount: Decimal,
    reference_id: str,
    description: str | None,
    transfer_id: UUID | None = None,
) -> Transaction:
    """Writes one ledger entry and updates the account balance accordingly.

    The single place where balances change. The caller must hold the account's row lock
    and own the surrounding DB transaction (so a failure here rolls everything back).
    """
    if type_ is TransactionType.DEBIT:
        if account.balance < amount:
            raise InsufficientBalanceError(account.id, account.balance, amount)
        new_balance = account.balance - amount
    else:
        new_balance = account.balance + amount
        if new_balance > MAX_BALANCE:
            raise BalanceLimitExceededError(account.id, MAX_BALANCE)

    entry = Transaction(
        account_id=account.id,
        type=type_.value,
        amount=amount,
        description=description,
        reference_id=reference_id,
        balance_after=new_balance,
        transfer_id=transfer_id,
    )
    db.add(entry)
    account.balance = new_balance
    db.flush()
    return entry


def _find_by_reference(db: Session, account_id: UUID, reference_id: str) -> Transaction | None:
    stmt = select(Transaction).where(
        Transaction.account_id == account_id, Transaction.reference_id == reference_id
    )
    return db.scalars(stmt).one_or_none()


def _snapshot(transaction: Transaction) -> dict[str, Any]:
    # Serialised while still inside the DB transaction: a rollback expires ORM objects.
    return TransactionResponse.model_validate(transaction).model_dump(mode="json")
