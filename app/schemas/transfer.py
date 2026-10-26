from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import examples
from app.schemas.account import BalanceResponse
from app.schemas.common import Amount, Description, Money, ReferenceId


class TransferCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "from_account_id": examples.ACCOUNT_ID,
                    "to_account_id": examples.OTHER_ACCOUNT_ID,
                    "amount": "30.00",
                    "reference_id": "rent-2026-10",
                    "description": "October rent",
                }
            ]
        },
    )

    from_account_id: UUID = Field(examples=[examples.ACCOUNT_ID])
    to_account_id: UUID = Field(examples=[examples.OTHER_ACCOUNT_ID])
    amount: Amount
    reference_id: ReferenceId = Field(
        description="Unique per source account. Re-sending it returns 409 and never moves the "
        "money twice.",
        examples=["rent-2026-10"],
    )
    description: Description | None = Field(
        default=None,
        description="Optional note (max 255 characters), also used on both ledger entries.",
        examples=["October rent"],
    )


class TransferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(examples=[examples.TRANSFER_ID])
    from_account_id: UUID = Field(examples=[examples.ACCOUNT_ID])
    to_account_id: UUID = Field(examples=[examples.OTHER_ACCOUNT_ID])
    amount: Money = Field(examples=["30.00"])
    reference_id: str = Field(examples=["rent-2026-10"])
    description: str | None = Field(examples=["October rent"])
    created_at: datetime = Field(examples=[examples.TIMESTAMP])


class TransferResult(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "transfer": examples.TRANSFER,
                    "from_account": {"account_id": examples.ACCOUNT_ID, "balance": "70.00"},
                    "to_account": {"account_id": examples.OTHER_ACCOUNT_ID, "balance": "80.00"},
                }
            ]
        }
    )

    transfer: TransferResponse
    from_account: BalanceResponse = Field(description="Source account balance after the transfer.")
    to_account: BalanceResponse = Field(
        description="Destination account balance after the transfer."
    )
