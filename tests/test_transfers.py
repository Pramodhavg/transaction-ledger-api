import uuid
from decimal import Decimal

import pytest

from app.schemas.transaction import TransactionType
from app.schemas.transfer import TransferCreate
from app.services import transfer_service
from tests.helpers import assert_error, count_rows, seed_balance


@pytest.fixture
def accounts(api):
    """Spec setup: A = 100, B = 50."""
    return api.create_account("A", opening="100"), api.create_account("B", opening="50")


def snapshot(api, engine, *account_ids):
    """Everything a failed transfer must leave untouched."""
    return (
        [api.balance(a) for a in account_ids],
        count_rows(engine, "transactions"),
        count_rows(engine, "transfers"),
    )


def test_transfer_moves_money(api, accounts):
    """Spec example: A = 100, B = 50, transfer 30 A -> B  =>  A = 70, B = 80."""
    a, b = accounts

    response = api.transfer(a, b, "30", reference_id="rent-1", description="Rent")

    assert response.status_code == 201
    body = response.json()
    assert body["from_account"] == {"account_id": a, "balance": "70.00"}
    assert body["to_account"] == {"account_id": b, "balance": "80.00"}
    assert body["transfer"]["amount"] == "30.00"
    assert body["transfer"]["reference_id"] == "rent-1"
    assert (api.balance(a), api.balance(b)) == ("70.00", "80.00")


def test_transfer_records_a_debit_and_a_credit_leg(api, accounts):
    a, b = accounts
    transfer_id = api.transfer(a, b, "30", description="Rent").json()["transfer"]["id"]

    debit = api.transactions(a)[0]
    credit = api.transactions(b)[0]

    assert (debit["type"], debit["amount"], debit["balance_after"]) == ("debit", "30.00", "70.00")
    assert (credit["type"], credit["amount"], credit["balance_after"]) == ("credit", "30.00", "80.00")
    assert debit["transfer_id"] == credit["transfer_id"] == transfer_id
    assert debit["reference_id"] == f"transfer:{transfer_id}:debit"
    assert credit["reference_id"] == f"transfer:{transfer_id}:credit"
    assert debit["description"] == credit["description"] == "Rent"


def test_legs_get_a_default_description(api, accounts):
    a, b = accounts
    api.transfer(a, b, "1")

    assert api.transactions(a)[0]["description"] == f"Transfer to {b}"
    assert api.transactions(b)[0]["description"] == f"Transfer from {a}"


def test_insufficient_balance_rejects_the_whole_transfer(api, engine, accounts):
    a, b = accounts
    before = snapshot(api, engine, a, b)

    error = assert_error(api.transfer(a, b, "150"), 422, "INSUFFICIENT_BALANCE")

    assert error["details"]["account_id"] == a
    assert snapshot(api, engine, a, b) == before


def test_whole_balance_can_be_transferred(api, accounts):
    a, b = accounts
    assert api.transfer(a, b, "100").status_code == 201
    assert (api.balance(a), api.balance(b)) == ("0.00", "150.00")


def test_same_account_transfer_is_rejected(api, engine, accounts):
    a, b = accounts
    before = snapshot(api, engine, a, b)

    assert_error(api.transfer(a, a, "10"), 400, "SAME_ACCOUNT_TRANSFER")
    assert snapshot(api, engine, a, b) == before


@pytest.mark.parametrize("missing_side", ["source", "destination"])
def test_both_accounts_must_exist(api, engine, accounts, missing_side):
    a, b = accounts
    missing = str(uuid.uuid4())
    source, destination = (missing, b) if missing_side == "source" else (a, missing)
    before = snapshot(api, engine, a, b)

    error = assert_error(api.transfer(source, destination, "10"), 404, "ACCOUNT_NOT_FOUND")

    assert error["details"]["account_id"] == missing
    assert snapshot(api, engine, a, b) == before


def test_duplicate_reference_returns_409_and_moves_no_money(api, engine, accounts):
    a, b = accounts
    original = api.transfer(a, b, "30", reference_id="rent-1").json()["transfer"]
    before = snapshot(api, engine, a, b)

    error = assert_error(api.transfer(a, b, "30", reference_id="rent-1"), 409, "DUPLICATE_TRANSFER")

    assert error["details"]["transfer"] == original
    assert snapshot(api, engine, a, b) == before


def test_same_reference_from_a_different_source_account_is_allowed(api, accounts):
    a, b = accounts
    assert api.transfer(a, b, "10", reference_id="r-1").status_code == 201
    assert api.transfer(b, a, "10", reference_id="r-1").status_code == 201


def test_transfer_and_transaction_references_do_not_collide(api, accounts):
    a, b = accounts
    assert api.credit(a, "1", reference_id="shared").status_code == 201
    assert api.transfer(a, b, "1", reference_id="shared").status_code == 201


@pytest.mark.parametrize(
    "overrides, code",
    [
        ({"from_account_id": "nope"}, "INVALID_ACCOUNT_ID"),
        ({"to_account_id": "nope"}, "INVALID_ACCOUNT_ID"),
        ({"amount": "0"}, "INVALID_AMOUNT"),
        ({"amount": "1.001"}, "INVALID_AMOUNT"),
        ({"reference_id": "   "}, "VALIDATION_ERROR"),
        ({"balance": "5"}, "VALIDATION_ERROR"),
    ],
)
def test_invalid_transfer_requests_return_400(client, accounts, overrides, code):
    a, b = accounts
    body = {"from_account_id": a, "to_account_id": b, "amount": "10", "reference_id": "r"} | overrides
    assert_error(client.post("/api/v1/transfers", json=body), 400, code)


def test_failure_on_the_credit_leg_rolls_back_the_debit(api, engine, session_factory, monkeypatch, accounts):
    """Atomicity: if the second half fails, the first half must not persist."""
    a, b = accounts
    before = snapshot(api, engine, a, b)
    real_post_entry = transfer_service.post_entry

    def fail_on_credit(db, account, type_, *args, **kwargs):
        if type_ is TransactionType.CREDIT:
            raise RuntimeError("simulated failure on the credit leg")
        return real_post_entry(db, account, type_, *args, **kwargs)

    monkeypatch.setattr(transfer_service, "post_entry", fail_on_credit)
    payload = TransferCreate(
        from_account_id=uuid.UUID(a), to_account_id=uuid.UUID(b), amount=Decimal("30"), reference_id="t"
    )

    with session_factory() as db, pytest.raises(RuntimeError):
        transfer_service.create_transfer(db, payload)

    assert snapshot(api, engine, a, b) == before


def test_destination_over_the_balance_limit_rolls_back_the_whole_transfer(api, engine):
    source = api.create_account("Source", opening="100")
    destination = api.create_account("Whale")
    seed_balance(engine, destination, Decimal("9999999999999999.99"))
    before = snapshot(api, engine, source, destination)

    assert_error(api.transfer(source, destination, "1"), 422, "BALANCE_LIMIT_EXCEEDED")
    assert snapshot(api, engine, source, destination) == before
