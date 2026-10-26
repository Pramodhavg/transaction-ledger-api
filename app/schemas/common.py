import math
from decimal import Decimal
from typing import Annotated, Any, Self

from pydantic import BaseModel, Field, PlainSerializer, StringConstraints

from app.core.errors import ErrorCode
from app.core.money import MAX_TRANSACTION_AMOUNT

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def _format_money(value: Decimal) -> str:
    return f"{value:.2f}"


# Money in responses is a string with exactly two decimals, e.g. "150.00".
# Many JSON clients (JavaScript included) parse numbers as binary floats and would silently
# lose precision; a string keeps the exact value.
Money = Annotated[Decimal, PlainSerializer(_format_money, return_type=str)]

# Money in requests: a JSON number or string, never converted through float.
Amount = Annotated[
    Decimal,
    Field(
        gt=0,
        le=MAX_TRANSACTION_AMOUNT,
        decimal_places=2,
        description="Positive amount with at most 2 decimal places (JSON number or string).",
        examples=["100.00"],
    ),
]

ReferenceId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]

Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)]


class Pagination(BaseModel):
    page: int = Field(examples=[1])
    page_size: int = Field(examples=[20])
    total_records: int = Field(examples=[42])
    total_pages: int = Field(examples=[3])
    has_next: bool = Field(examples=[True])
    has_previous: bool = Field(examples=[False])

    @classmethod
    def build(cls, page: int, page_size: int, total_records: int) -> Self:
        total_pages = math.ceil(total_records / page_size)
        return cls(
            page=page,
            page_size=page_size,
            total_records=total_records,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1,
        )


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    details: dict[str, Any] = {}


class ErrorResponse(BaseModel):
    """The shape of every error response."""

    error: ErrorBody
