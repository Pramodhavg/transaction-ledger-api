from collections.abc import Iterator
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def build_engine(url: str, **kwargs: Any) -> Engine:
    return create_engine(
        url,
        pool_pre_ping=True,
        # Pin the DB session to UTC so every timestamp is returned in UTC.
        connect_args={"options": "-c timezone=UTC"},
        **kwargs,
    )


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    # expire_on_commit=False: objects stay readable after commit without an extra SELECT.
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


engine = build_engine(get_settings().database_url)
SessionLocal = build_session_factory(engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed afterwards."""
    with SessionLocal() as session:
        yield session
