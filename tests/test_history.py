import uuid

import pytest
from sqlalchemy import text

from tests.helpers import assert_error


@pytest.fixture
def account_with_25_transactions(api):
    """15 credits of 10.00 and 10 debits of 1.00, interleaved; references t00..t24 in order."""
    account = api.create_account()
    for i in range(25):
        type_, amount = ("debit", "1.00") if i % 5 in (1, 3) else ("credit", "10.00")
        assert api.transact(account, type_, amount, reference_id=f"t{i:02}").status_code == 201
    return account


def test_defaults_return_both_types_on_page_1_of_size_20(api, account_with_25_transactions):
    body = api.history(account_with_25_transactions).json()

    assert len(body["data"]) == 20
    assert {t["type"] for t in body["data"]} == {"credit", "debit"}
    assert body["pagination"] == {
        "page": 1, "page_size": 20, "total_records": 25, "total_pages": 2,
        "has_next": True, "has_previous": False,
    }


@pytest.mark.parametrize("type_, expected_count", [("credit", 15), ("debit", 10)])
def test_filter_by_type(api, account_with_25_transactions, type_, expected_count):
    body = api.history(account_with_25_transactions, type=type_, limit=100).json()

    assert body["pagination"]["total_records"] == expected_count
    assert len(body["data"]) == expected_count
    assert {t["type"] for t in body["data"]} == {type_}


def test_sorted_latest_first(api, account_with_25_transactions):
    data = api.history(account_with_25_transactions, limit=100).json()["data"]

    assert [t["reference_id"] for t in data] == [f"t{i:02}" for i in reversed(range(25))]
    timestamps = [t["created_at"] for t in data]
    assert timestamps == sorted(timestamps, reverse=True)


def test_pagination_metadata_and_pages_cover_everything_once(api, account_with_25_transactions):
    pages = [api.history(account_with_25_transactions, page=p, limit=10).json() for p in (1, 2, 3)]

    assert [len(p["data"]) for p in pages] == [10, 10, 5]
    assert pages[1]["pagination"] == {
        "page": 2, "page_size": 10, "total_records": 25, "total_pages": 3,
        "has_next": True, "has_previous": True,
    }
    assert pages[2]["pagination"]["has_next"] is False
    ids = [t["id"] for p in pages for t in p["data"]]
    assert len(ids) == len(set(ids)) == 25


def test_pagination_metadata_respects_the_type_filter(api, account_with_25_transactions):
    body = api.history(account_with_25_transactions, type="debit", page=2, limit=4).json()

    assert len(body["data"]) == 4
    assert body["pagination"]["total_records"] == 10
    assert body["pagination"]["total_pages"] == 3


@pytest.mark.parametrize("page", [4, 99, 10**20])
def test_page_past_the_end_is_empty_with_correct_metadata(api, account_with_25_transactions, page):
    response = api.history(account_with_25_transactions, page=page, limit=10)

    assert response.status_code == 200
    assert response.json()["data"] == []
    assert response.json()["pagination"]["total_records"] == 25
    assert response.json()["pagination"]["total_pages"] == 3


def test_empty_history(api):
    body = api.history(api.create_account()).json()

    assert body["data"] == []
    assert body["pagination"]["total_records"] == 0
    assert body["pagination"]["total_pages"] == 0
    assert body["pagination"]["has_next"] is False


def test_equal_timestamps_are_ordered_by_id_descending(api, engine):
    """The id tiebreaker keeps the order deterministic, so pages never overlap or skip rows."""
    account = api.create_account()
    ids = sorted(uuid.uuid4() for _ in range(3))
    with engine.begin() as conn:
        for i, transaction_id in enumerate(ids):
            conn.execute(
                text(
                    "INSERT INTO transactions (id, account_id, type, amount, reference_id, balance_after, created_at) "
                    "VALUES (:id, :account, 'credit', 1, :ref, :after, '2026-01-01T00:00:00Z')"
                ),
                {"id": transaction_id, "account": account, "ref": f"r{i}", "after": i + 1},
            )
        conn.execute(text("UPDATE accounts SET balance = 3 WHERE id = :account"), {"account": account})

    data = api.history(account).json()["data"]

    assert [t["id"] for t in data] == [str(i) for i in reversed(ids)]


@pytest.mark.parametrize(
    "params",
    [{"page": 0}, {"page": -1}, {"page": "abc"}, {"page": 1.5}, {"page": ""},
     {"limit": 0}, {"limit": 101}, {"limit": -5}, {"limit": "x"}, {"page": 0, "limit": 0}],
)
def test_invalid_pagination_returns_400(api, params):
    assert_error(api.history(api.create_account(), **params), 400, "INVALID_PAGINATION")


def test_limit_of_100_is_allowed(api):
    assert api.history(api.create_account(), limit=100).status_code == 200


@pytest.mark.parametrize("type_", ["refund", "CREDIT", ""])
def test_invalid_type_filter_returns_400(api, type_):
    assert_error(api.history(api.create_account(), type=type_), 400, "INVALID_TRANSACTION_TYPE")


def test_mixed_query_errors_are_reported_together(api):
    error = assert_error(api.history(api.create_account(), type="refund", page=0), 400, "VALIDATION_ERROR")
    assert len(error["details"]["errors"]) == 2


def test_unknown_account_returns_404(api):
    assert_error(api.history(str(uuid.uuid4())), 404, "ACCOUNT_NOT_FOUND")


def test_malformed_account_id_returns_400(api):
    assert_error(api.history("not-a-uuid"), 400, "INVALID_ACCOUNT_ID")
