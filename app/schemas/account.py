from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.common import Money

AccountName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
    Field(description="Account holder name (1-100 characters).", examples=["Alice Johnson"]),
]


class AccountCreate(BaseModel):
    # extra="forbid": sending `balance`, `id` or `created_at` is rejected with a 400 instead of
    # being silently ignored. The balance always starts at 0 and only changes via transactions.
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"name": "Alice Johnson"}]})

    name: AccountName


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    balance: Money = Field(examples=["0.00"])
    created_at: datetime


class BalanceResponse(BaseModel):
    account_id: UUID
    balance: Money = Field(examples=["150.00"])
