from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import DbSession
from app.schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Pagination
from app.schemas.transaction import (
    TransactionCreate,
    TransactionListResponse,
    TransactionResponse,
    TransactionType,
)
from app.services import transaction_service

router = APIRouter(prefix="/accounts/{account_id}/transactions", tags=["Transactions"])


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a credit or debit")
def create_transaction(
    account_id: UUID, payload: TransactionCreate, db: DbSession
) -> TransactionResponse:
    """Credits or debits the account atomically and returns the new ledger entry."""
    transaction = transaction_service.create_transaction(db, account_id, payload)
    return TransactionResponse.model_validate(transaction)


@router.get("", summary="Get transaction history")
def list_transactions(
    account_id: UUID,
    db: DbSession,
    type_: Annotated[
        TransactionType | None,
        Query(alias="type", description="Only `credit` or only `debit`; omit for both."),
    ] = None,
    page: Annotated[int, Query(ge=1, description="1-based page number.")] = 1,
    limit: Annotated[
        int, Query(ge=1, le=MAX_PAGE_SIZE, description=f"Page size, 1-{MAX_PAGE_SIZE}.")
    ] = DEFAULT_PAGE_SIZE,
) -> TransactionListResponse:
    """Lists the account's transactions, newest first, one page at a time."""
    transactions, total = transaction_service.list_transactions(db, account_id, type_, page, limit)
    return TransactionListResponse(
        data=[TransactionResponse.model_validate(t) for t in transactions],
        pagination=Pagination.build(page=page, page_size=limit, total_records=total),
    )
