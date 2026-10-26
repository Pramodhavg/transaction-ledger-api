"""Database-level guarantees: they hold even for raw SQL that bypasses the application."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError


@pytest.fixture
def ledger(api):
    """Two accounts with a credit and a transfer between them."""
    a, b = api.create_account("A", opening="100"), api.create_account("B")
    api.transfer(a, b, "30")
    return a, b


def run_sql(engine, statement, **params):
    with engine.begin() as conn:
        conn.execute(text(statement), params)


# --- Immutability (trigger) ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE transactions SET amount = 1",
        "UPDATE transactions SET description = 'edited'",
        "UPDATE transactions SET created_at = now()",
        "DELETE FROM transactions",
        "UPDATE transfers SET amount = 1",
        "DELETE FROM transfers",
    ],
)
def test_ledger_rows_cannot_be_changed_even_with_raw_sql(engine, ledger, statement):
    with pytest.raises(IntegrityError, match="immutable"):
        run_sql(engine, statement)


def test_failed_modification_leaves_the_ledger_intact(api, engine, ledger):
    a, _ = ledger
    before = api.transactions(a)

    with pytest.raises(IntegrityError):
        run_sql(engine, "UPDATE transactions SET amount = amount * 2")

    assert api.transactions(a) == before


# --- Constraints -------------------------------------------------------------------------------


def test_balance_can_never_be_negative(engine, ledger):
    a, _ = ledger
    with pytest.raises(IntegrityError, match="ck_accounts_balance_non_negative"):
        run_sql(engine, "UPDATE accounts SET balance = -0.01 WHERE id = :id", id=a)


def test_account_name_cannot_be_blank(engine):
    with pytest.raises(IntegrityError, match="ck_accounts_name_not_blank"):
        run_sql(engine, "INSERT INTO accounts (name) VALUES ('   ')")


INSERT_TRANSACTION = (
    "INSERT INTO transactions (account_id, type, amount, reference_id, balance_after) "
    "VALUES (:account, :type, :amount, :ref, :after)"
)


@pytest.mark.parametrize(
    "overrides, constraint",
    [
        ({"amount": 0}, "ck_transactions_amount_positive"),
        ({"amount": -5}, "ck_transactions_amount_positive"),
        ({"type": "refund"}, "ck_transactions_type_valid"),
        ({"after": -1}, "ck_transactions_balance_after_non_negative"),
        ({"ref": "duplicate"}, "uq_transactions_account_id_reference_id"),
        ({"account": str(uuid.uuid4())}, "fk_transactions_account_id_accounts"),
    ],
)
def test_invalid_transactions_are_rejected_by_the_database(api, engine, overrides, constraint):
    account = api.create_account()
    api.credit(account, "1", reference_id="duplicate")
    params = {"account": account, "type": "credit", "amount": 1, "ref": "new", "after": 2} | overrides

    with pytest.raises(IntegrityError, match=constraint):
        run_sql(engine, INSERT_TRANSACTION, **params)


def test_transfer_to_the_same_account_is_rejected_by_the_database(engine, ledger):
    a, _ = ledger
    with pytest.raises(IntegrityError, match="ck_transfers_different_accounts"):
        run_sql(
            engine,
            "INSERT INTO transfers (from_account_id, to_account_id, amount, reference_id) "
            "VALUES (:a, :a, 1, 'self')",
            a=a,
        )


def test_balance_beyond_numeric_18_2_is_rejected_by_the_database(engine, api):
    """The column has a hard ceiling; the API turns this into 422 BALANCE_LIMIT_EXCEEDED."""
    account = api.create_account()
    with pytest.raises(DBAPIError, match="numeric field overflow"):
        run_sql(engine, "UPDATE accounts SET balance = 10000000000000000 WHERE id = :id", id=account)
