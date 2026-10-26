import uuid
from datetime import datetime, timedelta

import pytest

from tests.helpers import API, assert_error, count_rows


def test_create_account_starts_with_zero_balance(client):
    response = client.post(f"{API}/accounts", json={"name": "Alice Johnson"})

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Alice Johnson"
    assert body["balance"] == "0.00"
    uuid.UUID(body["id"])
    assert datetime.fromisoformat(body["created_at"]).utcoffset() == timedelta(0)


def test_account_ids_are_unique(api):
    ids = {api.create_account() for _ in range(5)}
    assert len(ids) == 5


def test_name_is_trimmed(client):
    response = client.post(f"{API}/accounts", json={"name": "  Bob  "})
    assert response.json()["name"] == "Bob"


def test_name_of_100_characters_is_accepted(client):
    assert client.post(f"{API}/accounts", json={"name": "x" * 100}).status_code == 201


@pytest.mark.parametrize(
    "field, value",
    [("balance", 500), ("balance", "0.00"), ("id", str(uuid.uuid4())), ("created_at", "2020-01-01T00:00:00Z")],
)
def test_client_cannot_set_system_fields(client, engine, field, value):
    response = client.post(f"{API}/accounts", json={"name": "Mallory", field: value})

    error = assert_error(response, 400, "VALIDATION_ERROR")
    assert error["details"]["errors"][0]["field"] == field
    assert count_rows(engine, "accounts") == 0


@pytest.mark.parametrize(
    "body",
    [{}, {"name": ""}, {"name": "   "}, {"name": "x" * 101}, {"name": 123}, {"name": None}],
    ids=["missing", "empty", "blank", "too-long", "number", "null"],
)
def test_invalid_name_is_rejected(client, engine, body):
    assert_error(client.post(f"{API}/accounts", json=body), 400, "VALIDATION_ERROR")
    assert count_rows(engine, "accounts") == 0


def test_get_account(api, client):
    account_id = api.create_account("Carol", opening="25.50")

    body = client.get(f"{API}/accounts/{account_id}").json()

    assert body["id"] == account_id
    assert body["name"] == "Carol"
    assert body["balance"] == "25.50"


def test_get_balance(api, client):
    account_id = api.create_account(opening="150")

    response = client.get(f"{API}/accounts/{account_id}/balance")

    assert response.status_code == 200
    assert response.json() == {"account_id": account_id, "balance": "150.00"}


@pytest.mark.parametrize("suffix", ["", "/balance"])
def test_unknown_account_returns_404(client, suffix):
    missing = str(uuid.uuid4())

    error = assert_error(client.get(f"{API}/accounts/{missing}{suffix}"), 404, "ACCOUNT_NOT_FOUND")
    assert error["details"]["account_id"] == missing


@pytest.mark.parametrize("suffix", ["", "/balance"])
def test_malformed_account_id_returns_400(client, suffix):
    assert_error(client.get(f"{API}/accounts/not-a-uuid{suffix}"), 400, "INVALID_ACCOUNT_ID")
