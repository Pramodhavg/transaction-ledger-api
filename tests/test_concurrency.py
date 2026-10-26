"""Concurrency tests: real threads, each with its own DB session and connection, calling the
services directly so the requests genuinely race inside Postgres."""

import threading
import uuid
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from app.core.errors import AppError
from app.schemas.transaction import TransactionCreate
from app.schemas.transfer import TransferCreate
from app.services import transaction_service, transfer_service
from tests.helpers import count_rows

OK = "OK"


def run_concurrently(count: int, action: Callable[[int], None]) -> Counter[str]:
    """Runs `action(i)` in `count` threads released at the same instant.

    Returns how often each outcome happened: OK or the error code. Any other exception
    (e.g. a deadlock) propagates and fails the test; the timeout turns a hang into a failure.
    """
    barrier = threading.Barrier(count)

    def worker(i: int) -> str:
        barrier.wait()
        try:
            action(i)
            return OK
        except AppError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = [pool.submit(worker, i) for i in range(count)]
        return Counter(future.result(timeout=60) for future in futures)


def post(session_factory, account_id: str, type_: str, amount: str, reference_id: str) -> None:
    payload = TransactionCreate(type=type_, amount=Decimal(amount), reference_id=reference_id)
    with session_factory() as db:
        transaction_service.create_transaction(db, uuid.UUID(account_id), payload)


def test_parallel_debits_never_overdraw(api, session_factory):
    """Balance 100, 20 simultaneous debits of 10: exactly 10 succeed and the balance ends at 0."""
    account = api.create_account(opening="100")

    outcomes = run_concurrently(20, lambda i: post(session_factory, account, "debit", "10", f"d{i}"))

    assert outcomes == {OK: 10, "INSUFFICIENT_BALANCE": 10}
    assert api.balance(account) == "0.00"
    debits = [t for t in api.transactions(account) if t["type"] == "debit"]
    # Each successful debit saw the previous one's result: 90, 80, ..., 0 (no lost updates).
    assert sorted(Decimal(t["balance_after"]) for t in debits) == [Decimal(n) for n in range(0, 100, 10)]


def test_parallel_requests_with_the_same_reference_create_one_transaction(api, engine, session_factory):
    account = api.create_account()

    outcomes = run_concurrently(10, lambda i: post(session_factory, account, "credit", "25", "same-ref"))

    assert outcomes == {OK: 1, "DUPLICATE_TRANSACTION": 9}
    assert api.balance(account) == "25.00"
    assert count_rows(engine, "transactions") == 1


def test_history_order_matches_the_order_balances_changed(api, session_factory):
    """Under contention, latest-first by created_at must agree with the balance_after chain."""
    account = api.create_account(opening="1000")

    outcomes = run_concurrently(
        30,
        lambda i: post(session_factory, account, "credit" if i % 2 else "debit", str(i + 1), f"m{i}"),
    )

    assert outcomes == {OK: 30}
    oldest_first = list(reversed(api.transactions(account)))
    running = Decimal(0)
    for entry in oldest_first:
        amount = Decimal(entry["amount"])
        running += amount if entry["type"] == "credit" else -amount
        assert Decimal(entry["balance_after"]) == running
    assert Decimal(api.balance(account)) == running


def test_opposite_transfers_do_not_deadlock_and_conserve_money(api, session_factory):
    """20 transfers A->B and 20 B->A at once. Without a fixed lock order these would deadlock."""
    a, b = api.create_account("A", opening="1000"), api.create_account("B", opening="1000")

    def transfer(i: int) -> None:
        source, destination = (a, b) if i % 2 == 0 else (b, a)
        payload = TransferCreate(
            from_account_id=uuid.UUID(source),
            to_account_id=uuid.UUID(destination),
            amount=Decimal("10"),
            reference_id=f"t{i}",
        )
        with session_factory() as db:
            transfer_service.create_transfer(db, payload)

    outcomes = run_concurrently(40, transfer)

    assert outcomes == {OK: 40}
    assert (api.balance(a), api.balance(b)) == ("1000.00", "1000.00")


def test_parallel_transfers_from_one_account_never_overdraw(api, session_factory):
    source = api.create_account("Source", opening="100")
    destinations = [api.create_account(f"D{i}") for i in range(4)]

    def transfer(i: int) -> None:
        payload = TransferCreate(
            from_account_id=uuid.UUID(source),
            to_account_id=uuid.UUID(destinations[i % 4]),
            amount=Decimal("30"),
            reference_id=f"t{i}",
        )
        with session_factory() as db:
            transfer_service.create_transfer(db, payload)

    outcomes = run_concurrently(12, transfer)

    assert outcomes == {OK: 3, "INSUFFICIENT_BALANCE": 9}
    assert api.balance(source) == "10.00"
    assert sum(Decimal(api.balance(d)) for d in destinations) == Decimal("90.00")
