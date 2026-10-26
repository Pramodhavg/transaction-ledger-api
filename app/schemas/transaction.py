from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.core.money import MAX_TRANSACTION_AMOUNT
from app.schemas.common import Money, Pagination

# Reserved for the two ledger legs of a transfer ("transfer:<id>:debit" / ":credit"), so a
# client reference can never collide with one.
TRANSFER_REFERENCE_PREFIX = "transfer:"


class TransactionType(StrEnum):
    CREDIT = "credit"
    DEBIT = "debit"


# Accepted as a JSON number or string; never converted through float.
Amount = Annotated[
    Decimal,
    Field(
        gt=0,
        le=MAX_TRANSACTION_AMOUNT,
        decimal_places=2,
        description="Positive amount with at most 2 decimal places (number or string).",
        examples=["100.00"],
    ),
]

ReferenceId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
    Field(
        description="Client-supplied unique reference for this transaction within the account. "
        "Re-sending the same reference returns 409 and never creates a second transaction.",
        examples=["deposit-001"],
    ),
]

Description = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=255),
    Field(description="Optional free-text note (max 255 characters).", examples=["Salary"]),
]


class TransactionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: TransactionType
    amount: Amount
    reference_id: ReferenceId
    description: Description | None = None

    @field_validator("reference_id")
    @classmethod
    def reject_reserved_prefix(cls, value: str) -> str:
        if value.startswith(TRANSFER_REFERENCE_PREFIX):
            raise ValueError(f"must not start with '{TRANSFER_REFERENCE_PREFIX}' (reserved for transfers)")
        return value


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_id: UUID
    type: TransactionType
    amount: Money = Field(examples=["100.00"])
    description: str | None
    reference_id: str
    balance_after: Money = Field(
        description="Account balance immediately after this transaction.", examples=["150.00"]
    )
    transfer_id: UUID | None = Field(description="Set when this entry is one leg of a transfer.")
    created_at: datetime


class TransactionListResponse(BaseModel):
    data: list[TransactionResponse]
    pagination: Pagination
