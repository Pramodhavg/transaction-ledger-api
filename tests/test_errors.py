"""Framework-level behaviour: error format everywhere, 404/405/500, health, docs.

Every other test file also checks the standard error shape through assert_error().
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db.session import get_db
from app.main import app
from app.services import account_service
from tests.helpers import API, assert_error


def test_health_reports_ok(client):
    response = client.get(f"{API}/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_reports_503_when_the_database_is_down(client):
    class UnreachableDatabase:
        def execute(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    def broken_db():
        yield UnreachableDatabase()

    app.dependency_overrides[get_db] = broken_db

    assert_error(client.get(f"{API}/health"), 503, "SERVICE_UNAVAILABLE")


def test_unknown_route_returns_404_in_standard_format(client):
    error = assert_error(client.get(f"{API}/does-not-exist"), 404, "NOT_FOUND")
    assert "does-not-exist" in error["message"]


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_transactions_cannot_be_edited_or_deleted_through_the_api(client, api, method):
    account = api.create_account()

    response = client.request(method, f"{API}/accounts/{account}/transactions")

    error = assert_error(response, 405, "METHOD_NOT_ALLOWED")
    assert error["details"]["allowed_methods"] == ["GET", "POST"]
    assert response.headers["allow"] == "GET, POST"


@pytest.mark.parametrize("method", ["GET", "PUT", "PATCH", "DELETE"])
def test_there_is_no_endpoint_for_a_single_transaction(client, api, method):
    account = api.create_account()
    transaction_id = api.credit(account, "10").json()["id"]

    response = client.request(method, f"{API}/accounts/{account}/transactions/{transaction_id}")

    assert_error(response, 404, "NOT_FOUND")


def test_accounts_cannot_be_deleted(client, api):
    assert_error(client.delete(f"{API}/accounts/{api.create_account()}"), 405, "METHOD_NOT_ALLOWED")


@pytest.mark.parametrize("body", ['{"name": "x"', "not json", ""])
def test_malformed_json_returns_400(client, body):
    response = client.post(f"{API}/accounts", content=body, headers={"Content-Type": "application/json"})
    assert_error(response, 400, "VALIDATION_ERROR")


def test_unexpected_errors_return_a_generic_500_without_internals(api, monkeypatch):
    account = api.create_account()

    def explode(*args, **kwargs):
        raise RuntimeError("secret internal detail: password=hunter2")

    monkeypatch.setattr(account_service, "get_account", explode)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(f"{API}/accounts/{account}")

    assert_error(response, 500, "INTERNAL_ERROR")
    for leak in ("secret", "hunter2", "RuntimeError", "Traceback"):
        assert leak not in response.text


def test_root_redirects_to_swagger(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/docs"


def test_openapi_documents_the_real_error_format(client):
    spec = client.get("/openapi.json").json()

    assert "HTTPValidationError" not in str(spec)
    assert "ErrorResponse" in spec["components"]["schemas"]
    post_transaction = spec["paths"][f"{API}/accounts/{{account_id}}/transactions"]["post"]
    assert set(post_transaction["responses"]) == {"201", "400", "404", "409", "422"}
