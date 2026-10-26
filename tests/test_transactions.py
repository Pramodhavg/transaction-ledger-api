import uuid
from decimal import Decimal

import pytest

from app.core.money import MAX_BALANCE
from app.schemas.transaction import TransactionCreate
from app.services import transaction_service
from tests.helpers import API, assert_error, count_rows, seed_balance

# --- Credit / debit -------------------------------------------------------------------------


def test_credit_increases_balance(api):
    account = api.create_account(opening="100")

    response = api.credit(account, "50")

    assert response.status_code == 201
    assert response.json()["balance_after"] == "150.00"
    assert api.balance(account) == "150.00"


def test_debit_decreases_balance(api):
    account = api.create_account(opening="100")

    response = api.debit(account, "30")

    assert response.status_code == 201
    assert response.json()["balance_after"] == "70.00"
    assert api.balance(account) == "70.00"


def test_debit_of_the_entire_balance_is_allowed(api):
    account = api.create_account(opening="100")
    assert api.debit(account, "100").status_code == 201
    assert api.balance(account) == "0.00"


def test_insufficient_balance_is_rejected_and_nothing_is_stored(api, engine):
    account = api.create_account(opening="100")

    error = assert_error(api.debit(account, "150"), 422, "INSUFFICIENT_BALANCE")

    assert error["details"] == {"account_id": account, "balance": "100.00", "requested_amount": "150.00"}
    assert api.balance(account) == "100.00"
    assert count_rows(engine, "transactions") == 1  # only the opening credit


def test_balance_equals_result_of_all_valid_transactions(api):
    """Spec example: 0 + 100 + 50 - 30 - 20 = 100 (a rejected debit in between changes nothing)."""
    account = api.create_account()
    steps = [("credit", "100"), ("credit", "50"), ("debit", "30"), ("debit", "1000"), ("debit", "20")]

    statuses = [api.transact(account, type_, amount).status_code for type_, amount in steps]

    assert statuses == [201, 201, 201, 422, 201]
    assert api.balance(account) == "100.00"
    oldest_first = list(reversed(api.transactions(account)))
    assert [t["balance_after"] for t in oldest_first] == ["100.00", "150.00", "120.00", "100.00"]


def test_response_contains_the_full_transaction(api):
    account = api.create_account()

    body = api.credit(account, "12.5", reference_id="dep-1", description="Salary").json()

    assert body["account_id"] == account
    assert body["type"] == "credit"
    assert body["amount"] == "12.50"
    assert body["reference_id"] == "dep-1"
    assert body["description"] == "Salary"
    assert body["balance_after"] == "12.50"
    assert body["transfer_id"] is None
    uuid.UUID(body["id"])


# --- Duplicates (idempotency) -----------------------------------------------------------------


def test_duplicate_reference_returns_409_with_original_and_changes_nothing(api, engine):
    account = api.create_account()
    original = api.credit(account, "100", reference_id="dep-1").json()

    retry = api.credit(account, "999", reference_id="dep-1")  # same reference, different amount

    error = assert_error(retry, 409, "DUPLICATE_TRANSACTION")
    assert error["details"]["transaction"] == original
    assert api.balance(account) == "100.00"
    assert count_rows(engine, "transactions") == 1


def test_duplicate_is_detected_before_the_balance_check(api):
    """Retrying a debit that already succeeded must say "already done", not "insufficient"."""
    account = api.create_account(opening="100")
    assert api.debit(account, "100", reference_id="wd-1").status_code == 201

    assert_error(api.debit(account, "100", reference_id="wd-1"), 409, "DUPLICATE_TRANSACTION")
    assert api.balance(account) == "0.00"


def test_same_reference_is_allowed_on_different_accounts(api):
    first, second = api.create_account("A"), api.create_account("B")

    assert api.credit(first, "10", reference_id="shared").status_code == 201
    assert api.credit(second, "20", reference_id="shared").status_code == 201
    assert (api.balance(first), api.balance(second)) == ("10.00", "20.00")


def test_rejected_transaction_reference_can_be_retried(api):
    """Rejected transactions are not stored, so their reference stays free."""
    account = api.create_account()
    assert_error(api.debit(account, "50", reference_id="wd-1"), 422, "INSUFFICIENT_BALANCE")
    api.credit(account, "100")

    assert api.debit(account, "50", reference_id="wd-1").status_code == 201


# --- Validation -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "amount, stored",
    [(10, "10.00"), (10.5, "10.50"), ("10.50", "10.50"), ("10", "10.00"), (0.01, "0.01"),
     ("1000000000.00", "1000000000.00")],
)
def test_amount_is_accepted_as_number_or_string(api, amount, stored):
    account = api.create_account()
    assert api.credit(account, amount).json()["amount"] == stored


@pytest.mark.parametrize(
    "amount",
    [0, -5, "-5", 10.005, "10.005", "abc", "", "NaN", "Infinity", True, None, [], 1000000000.01],
)
def test_invalid_amount_is_rejected(api, engine, amount):
    account = api.create_account()
    assert_error(api.credit(account, amount), 400, "INVALID_AMOUNT")
    assert count_rows(engine, "transactions") == 0


@pytest.mark.parametrize("type_", ["refund", "CREDIT", "", None, 1])
def test_invalid_transaction_type_is_rejected(api, type_):
    account = api.create_account()
    assert_error(api.transact(account, type_, "10"), 400, "INVALID_TRANSACTION_TYPE")


@pytest.mark.parametrize("reference_id", ["", "   ", "x" * 101, 123])
def test_invalid_reference_id_is_rejected(client, api, reference_id):
    account = api.create_account()
    body = {"type": "credit", "amount": "10", "reference_id": reference_id}
    response = client.post(f"{API}/accounts/{account}/transactions", json=body)
    assert_error(response, 400, "VALIDATION_ERROR")


def test_reference_id_is_required(client, api):
    account = api.create_account()
    response = client.post(f"{API}/accounts/{account}/transactions", json={"type": "credit", "amount": "10"})
    error = assert_error(response, 400, "VALIDATION_ERROR")
    assert error["details"]["errors"][0]["field"] == "reference_id"


def test_reserved_transfer_prefix_is_rejected(api):
    account = api.create_account()
    assert_error(api.credit(account, "10", reference_id="transfer:abc"), 400, "VALIDATION_ERROR")


@pytest.mark.parametrize("field", ["balance_after", "created_at", "id", "account_id", "transfer_id"])
def test_system_fields_cannot_be_sent(api, field):
    account = api.create_account()
    error = assert_error(api.credit(account, "10", **{field: "x"}), 400, "VALIDATION_ERROR")
    assert error["details"]["errors"][0]["field"] == field


def test_description_is_optional_trimmed_and_limited(api):
    account = api.create_account()
    assert api.credit(account, "1").json()["description"] is None
    assert api.credit(account, "1", description="  Salary  ").json()["description"] == "Salary"
    assert api.credit(account, "1", description="x" * 255).status_code == 201
    assert_error(api.credit(account, "1", description="x" * 256), 400, "VALIDATION_ERROR")


def test_unknown_account_returns_404(api):
    assert_error(api.credit(str(uuid.uuid4()), "10"), 404, "ACCOUNT_NOT_FOUND")


def test_malformed_account_id_returns_400(api):
    assert_error(api.credit("not-a-uuid", "10"), 400, "INVALID_ACCOUNT_ID")


def test_multiple_problems_are_reported_together(client, api):
    account = api.create_account()
    response = client.post(f"{API}/accounts/{account}/transactions", json={"type": "refund", "amount": 0})
    error = assert_error(response, 400, "VALIDATION_ERROR")
    assert {e["field"] for e in error["details"]["errors"]} == {"type", "amount", "reference_id"}


# --- Balance limit (NUMERIC(18, 2) maximum) ---------------------------------------------------


def test_credit_up_to_the_maximum_balance_is_allowed(api, engine):
    account = api.create_account()
    seed_balance(engine, account, Decimal("9999999999999999.00"))

    assert api.credit(account, "0.99").json()["balance_after"] == "9999999999999999.99"


def test_credit_above_the_maximum_balance_is_rejected(api, engine):
    account = api.create_account()
    seed_balance(engine, account, MAX_BALANCE)

    error = assert_error(api.credit(account, "0.01"), 422, "BALANCE_LIMIT_EXCEEDED")

    assert error["details"]["max_balance"] == "9999999999999999.99"
    assert api.balance(account) == "9999999999999999.99"
    assert count_rows(engine, "transactions") == 1  # only the seed
    assert api.debit(account, "0.99").status_code == 201  # the account still works


def test_database_numeric_overflow_is_reported_as_422_not_500(api, engine, monkeypatch):
    """Backstop: even if the application check were missing, Postgres' overflow error maps to 422."""
    monkeypatch.setattr(transaction_service, "MAX_BALANCE", Decimal("1e30"))  # disable the pre-check
    account = api.create_account()
    seed_balance(engine, account, Decimal("9999999999999999.00"))

    assert_error(api.credit(account, "1.00"), 422, "BALANCE_LIMIT_EXCEEDED")
    assert api.balance(account) == "9999999999999999.00"
    assert count_rows(engine, "transactions") == 1


# --- Atomicity ---------------------------------------------------------------------------------


def test_a_failure_after_the_insert_rolls_back_everything(api, engine, session_factory, monkeypatch):
    """The ledger row and the balance update are one atomic unit: if anything fails before
    commit, neither persists."""
    account = api.create_account(opening="100")
    real_post_entry = transaction_service.post_entry

    def crash_after_insert(*args, **kwargs):
        real_post_entry(*args, **kwargs)  # row inserted and balance updated (flushed, not committed)
        raise RuntimeError("simulated crash before commit")

    monkeypatch.setattr(transaction_service, "post_entry", crash_after_insert)
    payload = TransactionCreate(type="debit", amount=Decimal("30"), reference_id="boom")

    with session_factory() as db, pytest.raises(RuntimeError):
        transaction_service.create_transaction(db, uuid.UUID(account), payload)

    assert api.balance(account) == "100.00"
    assert count_rows(engine, "transactions") == 1  # only the opening credit
