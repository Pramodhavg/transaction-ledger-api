from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings, read from environment variables (e.g. DATABASE_URL)."""

    app_name: str = "Transaction Ledger API"
    database_url: str = "postgresql+psycopg://ledger:ledger@localhost:5432/ledger"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
