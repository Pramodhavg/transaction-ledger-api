import logging

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.api.openapi import strip_default_validation_responses
from app.api.router import api_router
from app.core.config import get_settings
from app.core.error_handlers import register_exception_handlers

API_DESCRIPTION = """
A ledger service: create accounts, post credits and debits, read balances and paginated
transaction history, and transfer money between accounts.

**Conventions**
- **Money** is returned as a string with two decimals (`"150.00"`) so no precision is lost
  in JSON clients. Amounts may be sent as a JSON number or a string, with at most 2 decimals.
- **Timestamps** are ISO-8601 in UTC.
- **Errors** always have the same shape, `{"error": {"code", "message", "details"}}`.
  Branch on `code`; `message` is for humans. `400` means the request itself is invalid,
  `422` means a valid request was refused by a business rule (e.g. insufficient balance).
- **Transactions are immutable**: there are no update or delete endpoints, and the database
  rejects any change to a stored transaction.
- **Idempotency**: re-sending a `reference_id` returns `409` with the original record and
  never creates a duplicate.
"""

OPENAPI_TAGS = [
    {"name": "Accounts", "description": "Create accounts and read balances."},
    {"name": "Transactions", "description": "Post credits/debits and read history."},
    {"name": "Transfers", "description": "Move money between two accounts atomically."},
    {"name": "Health", "description": "Liveness and database connectivity."},
]


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description=API_DESCRIPTION,
        openapi_tags=OPENAPI_TAGS,
    )
    app.include_router(api_router)
    register_exception_handlers(app)
    strip_default_validation_responses(app)

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/docs")

    return app


app = create_app()
