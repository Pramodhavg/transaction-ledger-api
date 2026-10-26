from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas import examples
from app.schemas.common import Amount, Description, Money, Pagination, ReferenceId

# Reserved for the two ledger legs of a transfer ("transfer:<id>:debit" / ":credit"), so a
# client reference can never collide with one.
TRANSFER_REFERENCE_PREFIX = "transfer:"


class TransactionType(StrEnum):
    CREDIT = "credit"
    DEBIT = "debit"


class TransactionCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "type": "credit",
                    "amount": "100.00",
                    "reference_id": "deposit-001",
                    "description": "Salary",
                }
            ]
        },
    )

    type: TransactionType
    amount: Amount
    reference_id: ReferenceId = Field(
        description="Unique per account. Re-sending it returns 409 and never creates a second "
        "transaction; other accounts may reuse it.",
        examples=["deposit-001"],
    )
    description: Description | None = Field(
        default=None, description="Optional note (max 255 characters).", examples=["Salary"]
    )

    @field_validator("reference_id")
    @classmethod
    def reject_reserved_prefix(cls, value: str) -> str:
        if value.startswith(TRANSFER_REFERENCE_PREFIX):
            raise ValueError(f"must not start with '{TRANSFER_REFERENCE_PREFIX}' (reserved for transfers)")
        return value


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(examples=[examples.TRANSACTION_ID])
    account_id: UUID = Field(examples=[examples.ACCOUNT_ID])
    type: TransactionType = Field(examples=["credit"])
    amount: Money = Field(examples=["100.00"])
    description: str | None = Field(examples=["Salary"])
    reference_id: str = Field(examples=["deposit-001"])
    balance_after: Money = Field(
        description="Account balance immediately after this transaction.", examples=["150.00"]
    )
    transfer_id: UUID | None = Field(
        description="Set when this entry is one leg of a transfer.", examples=[None]
    )
    created_at: datetime = Field(examples=[examples.TIMESTAMP])


class TransactionListResponse(BaseModel):
    data: list[TransactionResponse]
    pagination: Pagination
