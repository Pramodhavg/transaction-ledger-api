import uuid
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import Engine, text

API = "/api/v1"


def new_reference() -> str:
    return f"ref-{uuid.uuid4().hex[:12]}"


class LedgerApi:
    """Small wrapper around the HTTP API so tests read like the spec."""

    def __init__(self, client: TestClient) -> None:
        self.client = client

    def create_account(self, name: str = "Alice", opening: Any = None) -> str:
        response = self.client.post(f"{API}/accounts", json={"name": name})
        assert response.status_code == 201, response.text
        account_id: str = response.json()["id"]
        if opening is not None:
            assert self.credit(account_id, opening).status_code == 201
        return account_id

    # account_id is positional-only, so tests can also send an `account_id` body field via **extra.
    def transact(
        self, account_id: str, type_: Any, amount: Any, /, reference_id: Any = None, **extra: Any
    ) -> Response:
        body = {"type": type_, "amount": amount, "reference_id": reference_id or new_reference()}
        return self.client.post(f"{API}/accounts/{account_id}/transactions", json=body | extra)

    def credit(self, account_id: str, amount: Any, /, reference_id: Any = None, **extra: Any) -> Response:
        return self.transact(account_id, "credit", amount, reference_id, **extra)

    def debit(self, account_id: str, amount: Any, /, reference_id: Any = None, **extra: Any) -> Response:
        return self.transact(account_id, "debit", amount, reference_id, **extra)

    def transfer(
        self, from_id: str, to_id: str, amount: Any, reference_id: Any = None, **extra: Any
    ) -> Response:
        body = {
            "from_account_id": from_id,
            "to_account_id": to_id,
            "amount": amount,
            "reference_id": reference_id or new_reference(),
        }
        return self.client.post(f"{API}/transfers", json=body | extra)

    def balance(self, account_id: str) -> str:
        response = self.client.get(f"{API}/accounts/{account_id}/balance")
        assert response.status_code == 200, response.text
        return response.json()["balance"]

    def history(self, account_id: str, **params: Any) -> Response:
        return self.client.get(f"{API}/accounts/{account_id}/transactions", params=params)

    def transactions(self, account_id: str) -> list[dict[str, Any]]:
        response = self.history(account_id, limit=100)
        assert response.status_code == 200, response.text
        return response.json()["data"]


def assert_error(response: Response, status: int, code: str) -> dict[str, Any]:
    """Asserts the status, the error code and the standard error shape; returns the error."""
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}, body
    assert set(body["error"]) == {"code", "message", "details"}, body
    assert body["error"]["code"] == code, body
    return body["error"]


def count_rows(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        return conn.scalar(text(f"SELECT count(*) FROM {table}"))


def seed_balance(engine: Engine, account_id: str, amount: Decimal) -> None:
    """Gives a new account a huge balance directly in SQL (one API credit is capped at 1e9).

    Recorded as a ledger row so the reconciliation invariant still holds.
    """
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO transactions (account_id, type, amount, reference_id, balance_after) "
                "VALUES (:account, 'credit', :amount, 'seed', :amount)"
            ),
            {"account": account_id, "amount": amount},
        )
        conn.execute(
            text("UPDATE accounts SET balance = :amount WHERE id = :account AND balance = 0"),
            {"account": account_id, "amount": amount},
        )
