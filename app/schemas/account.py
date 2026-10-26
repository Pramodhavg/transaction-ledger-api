from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas import examples
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

    id: UUID = Field(examples=[examples.ACCOUNT_ID])
    name: str = Field(examples=["Alice Johnson"])
    balance: Money = Field(examples=["0.00"])
    created_at: datetime = Field(examples=[examples.TIMESTAMP])


class BalanceResponse(BaseModel):
    account_id: UUID = Field(examples=[examples.ACCOUNT_ID])
    balance: Money = Field(examples=["150.00"])
