import math
from decimal import Decimal
from typing import Annotated, Any, Self

from pydantic import BaseModel, PlainSerializer

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def _format_money(value: Decimal) -> str:
    return f"{value:.2f}"


# Money in responses is a string with exactly two decimals, e.g. "150.00".
# Many JSON clients (JavaScript included) parse numbers as binary floats and would silently
# lose precision; a string keeps the exact value.
Money = Annotated[Decimal, PlainSerializer(_format_money, return_type=str)]


class Pagination(BaseModel):
    page: int
    page_size: int
    total_records: int
    total_pages: int
    has_next: bool
    has_previous: bool

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
    code: str
    message: str
    details: dict[str, Any] = {}


class ErrorResponse(BaseModel):
    """The shape of every error response."""

    error: ErrorBody
