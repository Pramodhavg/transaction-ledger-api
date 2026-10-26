from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import DbSession
from app.schemas.account import AccountCreate, AccountResponse, BalanceResponse
from app.services import account_service

router = APIRouter(prefix="/accounts", tags=["Accounts"])


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create an account")
def create_account(payload: AccountCreate, db: DbSession) -> AccountResponse:
    """Creates an account with a zero balance. Only `name` may be sent."""
    account = account_service.create_account(db, payload)
    return AccountResponse.model_validate(account)


@router.get("/{account_id}", summary="Get account details")
def get_account(account_id: UUID, db: DbSession) -> AccountResponse:
    account = account_service.get_account(db, account_id)
    return AccountResponse.model_validate(account)


@router.get("/{account_id}/balance", summary="Get account balance")
def get_balance(account_id: UUID, db: DbSession) -> BalanceResponse:
    account = account_service.get_account(db, account_id)
    return BalanceResponse(account_id=account.id, balance=account.balance)
