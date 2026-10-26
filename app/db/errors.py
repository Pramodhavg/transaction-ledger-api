"""Helpers to recognise specific Postgres errors raised through SQLAlchemy."""

from sqlalchemy.exc import DBAPIError

NUMERIC_VALUE_OUT_OF_RANGE = "22003"


def constraint_name(exc: DBAPIError) -> str | None:
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def is_numeric_overflow(exc: DBAPIError) -> bool:
    return getattr(exc.orig, "sqlstate", None) == NUMERIC_VALUE_OUT_OF_RANGE
