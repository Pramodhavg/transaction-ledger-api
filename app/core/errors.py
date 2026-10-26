from enum import StrEnum
from http import HTTPStatus
from typing import Any
from uuid import UUID


class ErrorCode(StrEnum):
    """Machine-readable error codes. Clients should branch on these, not on messages."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_ACCOUNT_ID = "INVALID_ACCOUNT_ID"
    INVALID_PAGINATION = "INVALID_PAGINATION"
    INVALID_TRANSACTION_TYPE = "INVALID_TRANSACTION_TYPE"
    INVALID_AMOUNT = "INVALID_AMOUNT"
    SAME_ACCOUNT_TRANSFER = "SAME_ACCOUNT_TRANSFER"
    ACCOUNT_NOT_FOUND = "ACCOUNT_NOT_FOUND"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    DUPLICATE_TRANSACTION = "DUPLICATE_TRANSACTION"
    DUPLICATE_TRANSFER = "DUPLICATE_TRANSFER"
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    BALANCE_LIMIT_EXCEEDED = "BALANCE_LIMIT_EXCEEDED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


class AppError(Exception):
    """An expected, client-facing error, rendered as {"error": {code, message, details}}."""

    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR
    code: ErrorCode = ErrorCode.INTERNAL_ERROR

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class AccountNotFoundError(AppError):
    status_code = HTTPStatus.NOT_FOUND
    code = ErrorCode.ACCOUNT_NOT_FOUND

    def __init__(self, account_id: UUID) -> None:
        super().__init__(f"Account {account_id} was not found", {"account_id": str(account_id)})


class ServiceUnavailableError(AppError):
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = ErrorCode.SERVICE_UNAVAILABLE
