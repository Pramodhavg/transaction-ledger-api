from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import DbSession
from app.api.openapi import error_responses
from app.core.errors import ErrorCode, ServiceUnavailableError
from app.schemas.health import HealthResponse

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    summary="Health check",
    responses=error_responses(ErrorCode.SERVICE_UNAVAILABLE),
)
def health(db: DbSession) -> HealthResponse:
    """Reports whether the API is up and can reach the database (503 if it cannot)."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise ServiceUnavailableError("Database is unreachable") from exc
    return HealthResponse(status="ok", database="ok")
