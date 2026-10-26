"""Turns every error into the same JSON shape: {"error": {"code", "message", "details"}}."""

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import compile_path

from app.core.errors import AppError, ErrorCode

# Request fields whose validation failures get a more specific code than VALIDATION_ERROR.
FIELD_ERROR_CODES: dict[str, ErrorCode] = {
    "account_id": ErrorCode.INVALID_ACCOUNT_ID,
    "from_account_id": ErrorCode.INVALID_ACCOUNT_ID,
    "to_account_id": ErrorCode.INVALID_ACCOUNT_ID,
    "amount": ErrorCode.INVALID_AMOUNT,
    "type": ErrorCode.INVALID_TRANSACTION_TYPE,
    "page": ErrorCode.INVALID_PAGINATION,
    "limit": ErrorCode.INVALID_PAGINATION,
}


def error_response(
    status_code: int,
    code: ErrorCode,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "details": details or {}}}
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body), headers=headers)


async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message, exc.details)


async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI's default is 422 with its own format; we return 400 in our format.

    422 is reserved for business-rule failures (e.g. insufficient balance), so a 400 always
    means "fix your request" and a 422 always means "valid request, refused by the rules".
    """
    raw_errors = exc.errors()
    errors = [_describe(error) for error in raw_errors]
    codes = {_code_for(error) for error in raw_errors}
    code = codes.pop() if len(codes) == 1 else ErrorCode.VALIDATION_ERROR

    if len(errors) == 1:
        field, text = errors[0]["field"], errors[0]["message"]
        message = f"{field}: {text}" if field else text
    else:
        message = f"Request validation failed with {len(errors)} errors"
    return error_response(HTTPStatus.BAD_REQUEST, code, message, {"errors": errors})


async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Framework-level errors (unknown route, wrong method) in our format instead of {"detail"}."""
    route = f"{request.method} {request.url.path}"
    details: dict[str, Any] = {}
    headers = exc.headers
    if exc.status_code == HTTPStatus.NOT_FOUND:
        code, message = ErrorCode.NOT_FOUND, f"No endpoint matches {route}"
    elif exc.status_code == HTTPStatus.METHOD_NOT_ALLOWED:
        code, message = ErrorCode.METHOD_NOT_ALLOWED, f"Method not allowed: {route}"
        allowed = _allowed_methods(request) or _split_allow_header(exc.headers)
        details["allowed_methods"] = allowed
        headers = {"Allow": ", ".join(allowed)}
    elif exc.status_code < HTTPStatus.INTERNAL_SERVER_ERROR:
        code, message = ErrorCode.VALIDATION_ERROR, str(exc.detail)
    else:
        code, message = ErrorCode.INTERNAL_ERROR, "An unexpected error occurred"
    return error_response(exc.status_code, code, message, details, headers=headers)


def _allowed_methods(request: Request) -> list[str]:
    # The router only reports the methods of the first route on the path (e.g. POST but not
    # GET on /transactions), so read every method for this path from the API's own contract.
    methods: set[str] = set()
    for path, operations in request.app.openapi()["paths"].items():
        path_regex, _, _ = compile_path(path)
        if path_regex.match(request.url.path):
            methods |= {method.upper() for method in operations}
    return sorted(methods)


def _split_allow_header(headers: dict[str, str] | None) -> list[str]:
    allow = (headers or {}).get("Allow", "")
    return [method.strip() for method in allow.split(",") if method.strip()]


async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    """Last resort: a generic 500 that never exposes internals (no stack trace, no SQL).

    Starlette re-raises the exception after this handler, so the server still logs the full
    traceback for operators.
    """
    return error_response(
        HTTPStatus.INTERNAL_SERVER_ERROR,
        ErrorCode.INTERNAL_ERROR,
        "An unexpected error occurred. Please try again later.",
    )


def _code_for(error: dict[str, Any]) -> ErrorCode:
    if error["type"] == "extra_forbidden":
        return ErrorCode.VALIDATION_ERROR
    location = error["loc"]
    field = location[1] if len(location) > 1 else None
    return FIELD_ERROR_CODES.get(field, ErrorCode.VALIDATION_ERROR)


def _describe(error: dict[str, Any]) -> dict[str, Any]:
    location, *path = error["loc"]
    field = ".".join(str(part) for part in path) or None
    message = error["msg"].removeprefix("Value error, ")

    if error["type"] == "json_invalid":
        field, message = None, "Request body is not valid JSON"
    elif error["type"] == "missing" and field is None:
        message = "Request body is required"
    elif error["type"] == "extra_forbidden":
        message = "Unknown or read-only field; it cannot be set by the client"
    return {"field": field, "location": location, "message": message}


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(Exception, handle_unexpected_error)
