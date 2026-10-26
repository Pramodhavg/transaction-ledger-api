"""Swagger/OpenAPI helpers: documented error responses with examples, and removal of FastAPI's
default 422 entries (this API reports validation errors as 400 in its own format)."""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from http import HTTPStatus
from typing import Any
from uuid import UUID

from fastapi import FastAPI

from app.core.errors import (
    AccountNotFoundError,
    AppError,
    BalanceLimitExceededError,
    DuplicateTransactionError,
    DuplicateTransferError,
    ErrorCode,
    InsufficientBalanceError,
    SameAccountTransferError,
    ServiceUnavailableError,
)
from app.core.money import MAX_BALANCE
from app.schemas import examples
from app.schemas.common import ErrorResponse

INVALID_UUID_MESSAGE = "Input should be a valid UUID, invalid character: found `n` at 0"


@dataclass(frozen=True)
class ErrorExample:
    status: HTTPStatus
    code: ErrorCode
    message: str
    details: dict[str, Any]
    name: str  # label in Swagger's "Examples" dropdown


def field_error(
    code: ErrorCode, field: str, location: str, message: str, name: str | None = None
) -> ErrorExample:
    """A request-validation example. It must name a field that exists on the route."""
    return ErrorExample(
        status=HTTPStatus.BAD_REQUEST,
        code=code,
        message=f"{field}: {message}",
        details={"errors": [{"field": field, "location": location, "message": message}]},
        name=name or code,
    )


def _from_error(error: AppError) -> ErrorExample:
    # Built from the real exception classes, so documented messages cannot drift from the API.
    return ErrorExample(
        HTTPStatus(error.status_code), error.code, error.message, error.details, error.code
    )


_ACCOUNT = UUID(examples.ACCOUNT_ID)

# Defaults only for errors that do not depend on a route's fields. Field errors must be passed
# explicitly with field_error(), so every route documents its own fields.
_DEFAULT_EXAMPLES: dict[ErrorCode, ErrorExample] = {
    example.code: example
    for example in map(
        _from_error,
        [
            AccountNotFoundError(_ACCOUNT),
            SameAccountTransferError(_ACCOUNT),
            DuplicateTransactionError("deposit-001", examples.TRANSACTION),
            DuplicateTransferError("rent-2026-10", examples.TRANSFER),
            InsufficientBalanceError(_ACCOUNT, Decimal("100.00"), Decimal("150.00")),
            BalanceLimitExceededError(_ACCOUNT, MAX_BALANCE),
            ServiceUnavailableError("Database is unreachable"),
        ],
    )
}

INVALID_ACCOUNT_ID_IN_PATH = field_error(
    ErrorCode.INVALID_ACCOUNT_ID, "account_id", "path", INVALID_UUID_MESSAGE
)


def error_responses(*items: ErrorCode | ErrorExample) -> dict[int | str, dict[str, Any]]:
    """Builds a route's `responses=`: one entry per status, one Swagger example per item."""
    grouped: dict[HTTPStatus, list[ErrorExample]] = {}
    for item in items:
        example = item if isinstance(item, ErrorExample) else _DEFAULT_EXAMPLES[item]
        grouped.setdefault(example.status, []).append(example)

    responses: dict[int | str, dict[str, Any]] = {}
    for status, group in grouped.items():
        codes = dict.fromkeys(example.code for example in group)  # unique, in order
        responses[int(status)] = {
            "model": ErrorResponse,
            "description": f"{status.phrase}: " + ", ".join(f"`{code}`" for code in codes),
            "content": {
                "application/json": {
                    "examples": {
                        example.name: {
                            "summary": example.name,
                            "value": {
                                "error": {
                                    "code": example.code,
                                    "message": example.message,
                                    "details": example.details,
                                }
                            },
                        }
                        for example in group
                    }
                }
            },
        }
    return responses


def strip_default_validation_responses(app: FastAPI) -> None:
    """Removes the auto-generated "422 HTTPValidationError" entries, which would be misleading:
    invalid input is answered with 400 in the standard error format."""
    generate: Callable[[], dict[str, Any]] = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = generate()
            for path_item in schema["paths"].values():
                for operation in path_item.values():
                    responses = operation.get("responses", {})
                    if "HTTPValidationError" in str(responses.get("422", "")):
                        del responses["422"]
            for name in ("HTTPValidationError", "ValidationError"):
                schema.get("components", {}).get("schemas", {}).pop(name, None)
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]
