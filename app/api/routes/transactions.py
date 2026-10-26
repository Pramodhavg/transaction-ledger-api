from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import DbSession
from app.schemas.transaction import TransactionCreate, TransactionResponse
from app.services import transaction_service

router = APIRouter(prefix="/accounts/{account_id}/transactions", tags=["Transactions"])


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a credit or debit")
def create_transaction(
    account_id: UUID, payload: TransactionCreate, db: DbSession
) -> TransactionResponse:
    """Credits or debits the account atomically and returns the new ledger entry."""
    transaction = transaction_service.create_transaction(db, account_id, payload)
    return TransactionResponse.model_validate(transaction)
