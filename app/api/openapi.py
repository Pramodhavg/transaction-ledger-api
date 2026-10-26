"""Swagger/OpenAPI helpers: documented error responses with examples, and removal of FastAPI's
default 422 entries (this API reports validation errors as 400 in its own format)."""

from collections.abc import Callable
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI

from app.core.errors import ErrorCode
from app.schemas.common import ErrorResponse

EXAMPLE_ACCOUNT_ID = "3fa85f64-5717-4562-b3fc-2c963f66afa6"


def _field_error(field: str, location: str, message: str) -> tuple[str, dict[str, Any]]:
    return f"{field}: {message}", {
        "errors": [{"field": field, "location": location, "message": message}]
    }


# status, message, details: one realistic example per error code.
_ERROR_EXAMPLES: dict[ErrorCode, tuple[HTTPStatus, str, dict[str, Any]]] = {
    ErrorCode.VALIDATION_ERROR: (
        HTTPStatus.BAD_REQUEST,
        *_field_error("reference_id", "body", "Field required"),
    ),
    ErrorCode.INVALID_ACCOUNT_ID: (
        HTTPStatus.BAD_REQUEST,
        *_field_error("account_id", "path", "Input should be a valid UUID"),
    ),
    ErrorCode.INVALID_PAGINATION: (
        HTTPStatus.BAD_REQUEST,
        *_field_error("limit", "query", "Input should be less than or equal to 100"),
    ),
    ErrorCode.INVALID_TRANSACTION_TYPE: (
        HTTPStatus.BAD_REQUEST,
        *_field_error("type", "body", "Input should be 'credit' or 'debit'"),
    ),
    ErrorCode.INVALID_AMOUNT: (
        HTTPStatus.BAD_REQUEST,
        *_field_error("amount", "body", "Input should be greater than 0"),
    ),
    ErrorCode.SAME_ACCOUNT_TRANSFER: (
        HTTPStatus.BAD_REQUEST,
        "Source and destination accounts must be different",
        {"account_id": EXAMPLE_ACCOUNT_ID},
    ),
    ErrorCode.ACCOUNT_NOT_FOUND: (
        HTTPStatus.NOT_FOUND,
        f"Account {EXAMPLE_ACCOUNT_ID} was not found",
        {"account_id": EXAMPLE_ACCOUNT_ID},
    ),
    ErrorCode.DUPLICATE_TRANSACTION: (
        HTTPStatus.CONFLICT,
        "A transaction with reference_id 'deposit-001' already exists for this account",
        {"transaction": {"reference_id": "deposit-001", "amount": "100.00", "...": "..."}},
    ),
    ErrorCode.DUPLICATE_TRANSFER: (
        HTTPStatus.CONFLICT,
        "A transfer with reference_id 'rent-2026-10' already exists for this source account",
        {"transfer": {"reference_id": "rent-2026-10", "amount": "30.00", "...": "..."}},
    ),
    ErrorCode.INSUFFICIENT_BALANCE: (
        HTTPStatus.UNPROCESSABLE_ENTITY,
        "Insufficient balance: available 100.00, requested 150.00",
        {"account_id": EXAMPLE_ACCOUNT_ID, "balance": "100.00", "requested_amount": "150.00"},
    ),
    ErrorCode.BALANCE_LIMIT_EXCEEDED: (
        HTTPStatus.UNPROCESSABLE_ENTITY,
        "This credit would take the balance above the maximum of 9999999999999999.99",
        {"account_id": EXAMPLE_ACCOUNT_ID, "max_balance": "9999999999999999.99"},
    ),
    ErrorCode.SERVICE_UNAVAILABLE: (
        HTTPStatus.SERVICE_UNAVAILABLE,
        "Database is unreachable",
        {},
    ),
}


def error_responses(*codes: ErrorCode) -> dict[int | str, dict[str, Any]]:
    """Builds the `responses=` argument of a route: one entry per status, one example per code."""
    grouped: dict[HTTPStatus, list[ErrorCode]] = {}
    for code in codes:
        grouped.setdefault(_ERROR_EXAMPLES[code][0], []).append(code)
    return {
        int(status): {
            "model": ErrorResponse,
            "description": f"{status.phrase}: " + ", ".join(f"`{code}`" for code in group),
            "content": {"application/json": {"examples": {code: _example(code) for code in group}}},
        }
        for status, group in grouped.items()
    }


def _example(code: ErrorCode) -> dict[str, Any]:
    _, message, details = _ERROR_EXAMPLES[code]
    return {
        "summary": code,
        "value": {"error": {"code": code, "message": message, "details": details}},
    }


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
