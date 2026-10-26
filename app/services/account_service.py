from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AccountNotFoundError
from app.models import Account
from app.schemas.account import AccountCreate


def create_account(db: Session, data: AccountCreate) -> Account:
    # Only the name comes from the client; id, balance (0) and created_at are system-generated.
    account = Account(name=data.name)
    with db.begin():
        db.add(account)
    return account


def get_account(db: Session, account_id: UUID) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise AccountNotFoundError(account_id)
    return account


def lock_account(db: Session, account_id: UUID) -> Account:
    """Load an account with SELECT ... FOR UPDATE, locking its row until the DB transaction ends.

    Concurrent writers to the same account wait here, so a balance check and the balance
    update that follows can never interleave with another request (no lost updates, no
    overdrafts). Requests for other accounts are not blocked.
    """
    stmt = (
        select(Account)
        .where(Account.id == account_id)
        .with_for_update()
        # Always use the freshly locked row, even if this session loaded the account before.
        .execution_options(populate_existing=True)
    )
    account = db.scalars(stmt).one_or_none()
    if account is None:
        raise AccountNotFoundError(account_id)
    return account
