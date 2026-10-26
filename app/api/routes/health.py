from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import DbSession
from app.schemas.health import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Health check", response_model=HealthResponse)
def health(db: DbSession) -> HealthResponse | JSONResponse:
    """Reports whether the API is up and can reach the database."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "unavailable", "database": "unreachable"})
    return HealthResponse(status="ok", database="ok")
