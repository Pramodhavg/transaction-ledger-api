from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import DbSession
from app.api.openapi import error_responses
from app.core.errors import ErrorCode
from app.schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Pagination
from app.schemas.transaction import (
    TransactionCreate,
    TransactionListResponse,
    TransactionResponse,
    TransactionType,
)
from app.services import transaction_service

router = APIRouter(prefix="/accounts/{account_id}/transactions", tags=["Transactions"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a credit or debit",
    response_description="The new ledger entry, including the resulting balance.",
    responses=error_responses(
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.INVALID_ACCOUNT_ID,
        ErrorCode.INVALID_TRANSACTION_TYPE,
        ErrorCode.INVALID_AMOUNT,
        ErrorCode.ACCOUNT_NOT_FOUND,
        ErrorCode.DUPLICATE_TRANSACTION,
        ErrorCode.INSUFFICIENT_BALANCE,
        ErrorCode.BALANCE_LIMIT_EXCEEDED,
    ),
)
def create_transaction(
    account_id: UUID, payload: TransactionCreate, db: DbSession
) -> TransactionResponse:
    """Credits (adds to) or debits (subtracts from) the account balance.

    - The ledger entry and the balance update are one atomic operation.
    - A debit larger than the balance is rejected with `INSUFFICIENT_BALANCE`; nothing is stored.
    - `reference_id` is unique per account. Re-sending it returns `409 DUPLICATE_TRANSACTION`
      with the original transaction in `details.transaction`, and changes nothing, so a
      client can safely retry after a timeout. Other accounts may reuse the same reference.
    - Transactions are immutable: there is no endpoint to edit or delete them.
    """
    transaction = transaction_service.create_transaction(db, account_id, payload)
    return TransactionResponse.model_validate(transaction)


@router.get(
    "",
    summary="Get transaction history",
    responses=error_responses(
        ErrorCode.INVALID_ACCOUNT_ID,
        ErrorCode.INVALID_PAGINATION,
        ErrorCode.INVALID_TRANSACTION_TYPE,
        ErrorCode.ACCOUNT_NOT_FOUND,
    ),
)
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
    """Lists the account's transactions, newest first (`created_at`, then `id`), one page at a
    time. A page past the end returns an empty `data` list with accurate `pagination`."""
    transactions, total = transaction_service.list_transactions(db, account_id, type_, page, limit)
    return TransactionListResponse(
        data=[TransactionResponse.model_validate(t) for t in transactions],
        pagination=Pagination.build(page=page, page_size=limit, total_records=total),
    )
