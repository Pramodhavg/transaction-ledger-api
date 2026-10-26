"""Test setup: a real Postgres test database, migrated with the real Alembic migration.

Run with:  docker compose run --rm api pytest -v
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.session import build_engine, build_session_factory, get_db
from app.main import app
from tests.helpers import LedgerApi

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")

# Invariants checked after EVERY test, so any code path that breaks the ledger fails loudly.
LEDGER_VIOLATIONS_SQL = text(
    """
    SELECT 'balance != sum(credits) - sum(debits)' AS problem, a.id::text AS subject
    FROM accounts a LEFT JOIN transactions t ON t.account_id = a.id
    GROUP BY a.id, a.balance
    HAVING a.balance <> COALESCE(SUM(CASE WHEN t.type = 'credit' THEN t.amount ELSE -t.amount END), 0)
    UNION ALL
    SELECT 'balance != latest balance_after', a.id::text
    FROM accounts a
    JOIN LATERAL (
        SELECT balance_after FROM transactions
        WHERE account_id = a.id ORDER BY created_at DESC, id DESC LIMIT 1
    ) latest ON true
    WHERE latest.balance_after <> a.balance
    UNION ALL
    SELECT 'transfer without exactly one debit and one credit leg', tr.id::text
    FROM transfers tr LEFT JOIN transactions t ON t.transfer_id = tr.id
    GROUP BY tr.id
    HAVING count(*) FILTER (WHERE t.type = 'debit' AND t.account_id = tr.from_account_id) <> 1
        OR count(*) FILTER (WHERE t.type = 'credit' AND t.account_id = tr.to_account_id) <> 1
        OR count(t.id) <> 2
    """
)


def _ensure_database_exists(url: str) -> None:
    target = make_url(url)
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target.database}
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    admin.dispose()


def _run_migrations(url: str) -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.downgrade(config, "base")  # also proves the downgrade works
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    if not TEST_DATABASE_URL:
        pytest.exit("TEST_DATABASE_URL is not set. Run: docker compose run --rm api pytest -v")
    if make_url(TEST_DATABASE_URL).database == make_url(get_settings().database_url).database:
        pytest.exit("TEST_DATABASE_URL points at the application database; refusing to wipe it.")

    _ensure_database_exists(TEST_DATABASE_URL)
    _run_migrations(TEST_DATABASE_URL)
    # Large pool: the concurrency tests hold one connection per thread.
    test_engine = build_engine(TEST_DATABASE_URL, pool_size=20, max_overflow=40)
    yield test_engine
    test_engine.dispose()


@pytest.fixture(scope="session")
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return build_session_factory(engine)


@pytest.fixture(autouse=True)
def clean_database_and_check_ledger(engine: Engine) -> Iterator[None]:
    # The immutability trigger is row-level, so TRUNCATE (an admin operation) still works.
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE transactions, transfers, accounts"))
    yield
    with engine.connect() as conn:
        violations = conn.execute(LEDGER_VIOLATIONS_SQL).all()
    assert not violations, f"Ledger invariant violated: {violations}"


@pytest.fixture
def client(session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    def get_test_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = get_test_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def api(client: TestClient) -> LedgerApi:
    return LedgerApi(client)
