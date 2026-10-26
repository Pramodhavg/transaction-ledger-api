from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, PlainSerializer


def _format_money(value: Decimal) -> str:
    return f"{value:.2f}"


# Money in responses is a string with exactly two decimals, e.g. "150.00".
# Many JSON clients (JavaScript included) parse numbers as binary floats and would silently
# lose precision; a string keeps the exact value.
Money = Annotated[Decimal, PlainSerializer(_format_money, return_type=str)]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = {}


class ErrorResponse(BaseModel):
    """The shape of every error response."""

    error: ErrorBody
