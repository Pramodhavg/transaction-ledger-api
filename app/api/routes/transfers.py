from fastapi import APIRouter, status

from app.api.deps import DbSession
from app.api.openapi import INVALID_UUID_MESSAGE, error_responses, field_error
from app.core.errors import ErrorCode
from app.schemas.account import BalanceResponse
from app.schemas.transfer import TransferCreate, TransferResponse, TransferResult
from app.services import transfer_service

router = APIRouter(prefix="/transfers", tags=["Transfers"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Transfer money between accounts",
    response_description="The transfer record and both accounts' new balances.",
    responses=error_responses(
        field_error(ErrorCode.VALIDATION_ERROR, "reference_id", "body", "Field required"),
        field_error(ErrorCode.INVALID_ACCOUNT_ID, "to_account_id", "body", INVALID_UUID_MESSAGE),
        field_error(ErrorCode.INVALID_AMOUNT, "amount", "body", "Input should be greater than 0"),
        ErrorCode.SAME_ACCOUNT_TRANSFER,
        ErrorCode.ACCOUNT_NOT_FOUND,
        ErrorCode.DUPLICATE_TRANSFER,
        ErrorCode.INSUFFICIENT_BALANCE,
        ErrorCode.BALANCE_LIMIT_EXCEEDED,
    ),
)
def create_transfer(payload: TransferCreate, db: DbSession) -> TransferResult:
    """Debits the source account and credits the destination account as one atomic operation.

    - Both accounts must exist and be different; the source needs a sufficient balance.
    - Either everything is written (transfer record, debit entry, credit entry, both balances)
      or nothing is. A partial transfer is impossible.
    - Each side appears in its account's history as a normal transaction with `transfer_id`
      set and `reference_id` `transfer:<transfer_id>:debit` / `:credit`.
    - `reference_id` is unique per source account: re-sending it returns
      `409 DUPLICATE_TRANSFER` with the original transfer and moves no money.
    """
    transfer, source, destination = transfer_service.create_transfer(db, payload)
    return TransferResult(
        transfer=TransferResponse.model_validate(transfer),
        from_account=BalanceResponse(account_id=source.id, balance=source.balance),
        to_account=BalanceResponse(account_id=destination.id, balance=destination.balance),
    )
