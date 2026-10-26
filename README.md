# Transaction Ledger API

A ledger backend for accounts, credits and debits, balances, paginated transaction history and atomic transfers between accounts. It is built with **FastAPI + PostgreSQL** and is designed to stay correct under concurrent requests, with integrity enforced by the database itself, not just by application code.

```bash
docker compose up --build                # API on http://localhost:8000, Swagger UI at /docs
docker compose run --rm api pytest -v    # 159 tests against a real Postgres database
```

## Highlights

| | |
|---|---|
| **Safe under concurrency** | Each account row is locked during a write (`SELECT … FOR UPDATE`). In the tests, 20 simultaneous debits of 10 against a balance of 100 produce exactly 10 successes, and the balance ends at `0.00`, never negative. |
| **Deadlock-free transfers** | Both accounts are always locked in the same order (sorted by id). In the tests, 40 transfers A→B and B→A run at the same moment with no deadlocks, and no money is created or lost. |
| **Atomic** | A ledger entry and its balance update (and both sides of a transfer) commit in one database transaction. Tests inject failures mid-transaction to show nothing persists. |
| **Idempotent writes** | `reference_id` is unique per account (a database constraint). Re-sending a request returns `409` with the original transaction and changes nothing. |
| **Immutable ledger** | There are no edit or delete endpoints, and a Postgres trigger rejects any `UPDATE` or `DELETE` on ledger rows, even from raw SQL. |
| **Integrity in the database** | `CHECK (balance >= 0)`, `CHECK (amount > 0)`, `UNIQUE (account_id, reference_id)`, foreign keys and named constraints. They hold even if application code were wrong. |
| **Exact money** | `NUMERIC(18,2)` in Postgres and `Decimal` in Python, never float. Amounts are returned as strings (`"150.00"`), so JSON clients can't lose precision. |
| **One error format** | `{"error": {"code", "message", "details"}}` for every error, including 404, 405 and 500. No stack traces are ever exposed. |
| **Tests that prove it** | 159 tests on real Postgres, with every balance reconciled against the ledger after each test. The concurrency tests are [shown to fail](#proof-that-the-tests-catch-real-bugs) when the locking is removed. |

## Quick start

**Prerequisite:** Docker with Compose v2. On Windows and macOS this is Docker Desktop. No local Python or Postgres is needed.

```bash
git clone <repository-url>
cd transaction-ledger-api
docker compose up --build
```

The commands are the same in PowerShell, macOS and Linux. On startup the API waits for Postgres to be healthy, applies the database migrations, and starts serving.

| URL | What |
|---|---|
| http://localhost:8000/docs | Swagger UI: interactive docs, try every endpoint |
| http://localhost:8000/redoc | ReDoc: the same docs as a reading view |
| http://localhost:8000/api/v1/health | Health check, including the database connection |

- **Stop:** press `Ctrl+C`.
- **Run in the background:** add `-d`.
- **Fresh start:** `docker compose down -v` also deletes the database volume.
- **Port 8000 already in use:** copy `.env.example` to `.env` and set `API_PORT`.

## Testing

```bash
docker compose run --rm api pytest -v
```

Expected: **`159 passed`** in about 15 seconds. The tests run in a throwaway container against a separate `ledger_test` database, which is created and migrated automatically, so your data is never touched. After changing code, add `--build` so the image is rebuilt.

| File | Tests | What it proves |
|---|---|---|
| `test_transactions.py` | 53 | Credit/debit math; the spec example `0 +100 +50 −30 −20 = 100`; insufficient balance stores nothing; duplicate references return the original and change nothing; every validation rule; the balance limit; rollback after a simulated crash |
| `test_history.py` | 28 | Type filter, newest-first order, pagination metadata, no overlap between pages, deterministic tie-breaking, invalid page/limit |
| `test_accounts.py` | 20 | Balance always starts at 0; `balance`, `id` and `created_at` can't be set by the client; name rules; 404 and 400 cases |
| `test_transfers.py` | 19 | Spec example `A=100, B=50, 30 A→B ⇒ A=70, B=80`; both ledger legs recorded; every failure leaves nothing changed; rollback when the credit leg fails |
| `test_errors.py` | 17 | One error format for 404, 405 and 500; no edit or delete routes exist; a 500 never leaks internals; health returns 503 when the DB is down |
| `test_integrity.py` | 17 | Raw SQL `UPDATE`/`DELETE` on ledger rows is blocked by the trigger; every CHECK, UNIQUE and foreign-key constraint is enforced by Postgres |
| `test_concurrency.py` | 5 | Parallel debits, parallel duplicates, opposite transfers, contended history order |

**How the tests run:**
- **Real Postgres, real migration.** The test database is built by running the actual Alembic migration (down, then up), so the trigger and constraints under test are exactly what production gets.
- **Reconciliation after every test.** An automatic fixture checks that every account's balance equals Σ credits − Σ debits and the latest `balance_after`, and that every transfer has exactly one debit and one credit leg. Any code path that corrupts the ledger fails the test that caused it.
- **Concurrency tests use real threads.** Each thread has its own database connection, and all are released at the same instant by a barrier, so requests genuinely race inside Postgres. They prove:
  - 20 parallel debits of 10 against 100 give exactly 10 successes and a final balance of 0. Each successful debit saw the previous one's result (no lost updates).
  - 10 parallel requests with the same `reference_id` create exactly one transaction.
  - 40 opposite transfers (A→B and B→A at once) complete without a deadlock, and money is conserved.
  - Under contention, newest-first history order still matches the order balances actually changed.

### Proof that the tests catch real bugs

To check that the concurrency tests aren't passing by luck, the code was deliberately broken in a throwaway container (the repository was not modified) and the tests were run again:

| Sabotage | Result |
|---|---|
| Removed `FOR UPDATE` from the account lock | **4 of 5 concurrency tests fail**, and the after-every-test reconciliation reports lost updates (balance ≠ sum of the ledger). The 5th test, duplicate reference, still passes because the `UNIQUE` constraint alone guarantees it, which shows the database backstop works. |
| Locked transfer accounts in request order instead of sorted order | Postgres raises a real **`DeadlockDetected`** in the A↔B transfer test. |

## API at a glance

All endpoints are under `/api/v1`. The full reference with request and response examples is in **[API.md](API.md)**.

| Method | Path | Success |
|---|---|---|
| `POST` | `/accounts` | `201` the account, balance `"0.00"` |
| `GET` | `/accounts/{account_id}` | `200` the account |
| `GET` | `/accounts/{account_id}/balance` | `200` `{account_id, balance}` |
| `POST` | `/accounts/{account_id}/transactions` | `201` the transaction, including `balance_after` |
| `GET` | `/accounts/{account_id}/transactions?type=&page=&limit=` | `200` `{data, pagination}`, newest first |
| `POST` | `/transfers` | `201` the transfer and both new balances |
| `GET` | `/health` | `200` `{status, database}` |

Errors use one shape everywhere:

```json
{"error": {"code": "INSUFFICIENT_BALANCE",
           "message": "Insufficient balance: available 100.00, requested 150.00",
           "details": {"account_id": "…", "balance": "100.00", "requested_amount": "150.00"}}}
```

| Status | Meaning | Codes |
|---|---|---|
| `400` | The request itself is invalid | `VALIDATION_ERROR`, `INVALID_ACCOUNT_ID`, `INVALID_AMOUNT`, `INVALID_TRANSACTION_TYPE`, `INVALID_PAGINATION`, `SAME_ACCOUNT_TRANSFER` |
| `404` | Not found | `ACCOUNT_NOT_FOUND`, `NOT_FOUND` (unknown route) |
| `405` | Method not allowed | `METHOD_NOT_ALLOWED` |
| `409` | Already processed | `DUPLICATE_TRANSACTION`, `DUPLICATE_TRANSFER` |
| `422` | Valid request, refused by a business rule | `INSUFFICIENT_BALANCE`, `BALANCE_LIMIT_EXCEEDED` |
| `500` / `503` | Server-side problem | `INTERNAL_ERROR`, `SERVICE_UNAVAILABLE` |

## Try it

**bash** (macOS, Linux, or Git Bash on Windows; uses [`jq`](https://jqlang.org/)):

```bash
BASE=http://localhost:8000/api/v1
A=$(curl -s -X POST $BASE/accounts -H 'Content-Type: application/json' -d '{"name":"Alice"}' | jq -r .id)
B=$(curl -s -X POST $BASE/accounts -H 'Content-Type: application/json' -d '{"name":"Bob"}' | jq -r .id)

# Credit 100 → 201, "balance_after": "100.00"
curl -s -X POST $BASE/accounts/$A/transactions -H 'Content-Type: application/json' \
  -d '{"type":"credit","amount":"100.00","reference_id":"dep-1","description":"Salary"}' | jq

# Same reference again → 409 DUPLICATE_TRANSACTION with the original; balance unchanged
curl -s -X POST $BASE/accounts/$A/transactions -H 'Content-Type: application/json' \
  -d '{"type":"credit","amount":"100.00","reference_id":"dep-1"}' | jq .error.code

# Overdraft → 422 INSUFFICIENT_BALANCE
curl -s -X POST $BASE/accounts/$A/transactions -H 'Content-Type: application/json' \
  -d '{"type":"debit","amount":"150.00","reference_id":"wd-1"}' | jq .error.code

# Transfer 30 → A 70.00, B 30.00
curl -s -X POST $BASE/transfers -H 'Content-Type: application/json' \
  -d "{\"from_account_id\":\"$A\",\"to_account_id\":\"$B\",\"amount\":\"30.00\",\"reference_id\":\"rent-1\"}" | jq

# History: newest first, filtered and paginated
curl -s "$BASE/accounts/$A/transactions?type=debit&page=1&limit=10" | jq
```

**PowerShell** (Windows):

```powershell
$base = "http://localhost:8000/api/v1"
$a = Invoke-RestMethod -Method Post "$base/accounts" -ContentType 'application/json' -Body '{"name":"Alice"}'
$b = Invoke-RestMethod -Method Post "$base/accounts" -ContentType 'application/json' -Body '{"name":"Bob"}'
Invoke-RestMethod -Method Post "$base/accounts/$($a.id)/transactions" -ContentType 'application/json' -Body '{"type":"credit","amount":"100.00","reference_id":"dep-1"}'
$transfer = @{ from_account_id = $a.id; to_account_id = $b.id; amount = "30.00"; reference_id = "rent-1" } | ConvertTo-Json
Invoke-RestMethod -Method Post "$base/transfers" -ContentType 'application/json' -Body $transfer | ConvertTo-Json -Depth 5
Invoke-RestMethod "$base/accounts/$($a.id)/transactions?limit=10" | ConvertTo-Json -Depth 5
```

PowerShell reports 4xx responses as errors. Swagger UI is the easiest way to explore the error cases.

**VS Code / JetBrains:** [`requests.http`](requests.http) walks through every endpoint and error case. In VS Code it uses the REST Client extension. To use Postman instead, import `http://localhost:8000/openapi.json`.

## Key design decisions

Each decision with its reasoning and the alternatives considered is in **[docs/DESIGN_DECISIONS.md](docs/DESIGN_DECISIONS.md)**. In short:

- **Pessimistic row locks per account.** Concurrent writes to one account take turns, so a balance check and the update that follows can't interleave with another request. Writes to different accounts don't block each other. The locks live in Postgres, so this stays correct with any number of API workers.
- **Sorted lock order for transfers.** A global lock order makes deadlocks between opposite transfers impossible.
- **Check under the lock, constraint as a backstop.** Duplicate and balance checks run while the row is locked, and `UNIQUE` and `CHECK` constraints catch anything that slips through.
- **Stored balance plus `balance_after` on each row.** Balance reads are O(1), and every transaction records the resulting balance, so the ledger can be audited and replayed.
- **Ordering by `created_at DESC, id DESC`, with `created_at` set by `clock_timestamp()`.** The time is taken *after* the lock is acquired, so history order matches the order balances actually changed.
- **`400` for invalid input, `422` for business rules.** FastAPI's default 422 is replaced, so each status has exactly one meaning.
- **Rejected requests are not stored**, so the ledger contains only entries that affected a balance.

## Tech stack

| | Why |
|---|---|
| **FastAPI** 0.162 + **Pydantic** 2.14 | Declarative validation and generated OpenAPI docs |
| **PostgreSQL** 16 | Row-level locks, CHECK constraints, triggers, exact `NUMERIC` |
| **SQLAlchemy** 2.0 (sync) + **psycopg** 3 | Explicit transaction boundaries. Requests are short and DB-bound, so async would add complexity without improving correctness. |
| **Alembic** | Versioned, reviewable schema, including the immutability trigger |
| **pytest** | Runs against real Postgres, including multi-threaded concurrency tests |
| **Docker Compose** | One command to run, with a healthcheck-gated startup |

## Project structure

```
app/
  main.py                  app factory: routers, error handlers, OpenAPI metadata
  api/routes/              thin HTTP handlers: accounts, transactions, transfers, health
  api/openapi.py           documented error examples; removes FastAPI's default 422
  services/                business rules: account_service, transaction_service, transfer_service
  models/                  SQLAlchemy models (mirror the migration)
  schemas/                 Pydantic request/response models, money type, pagination
  core/                    settings, error codes and exceptions, error handlers, money limits
  db/                      engine, session dependency, Postgres error helpers
alembic/versions/          0001: tables, named constraints, history index, immutability trigger
tests/                     159 tests, fixtures with per-test ledger reconciliation
docs/DESIGN_DECISIONS.md   decisions, reasoning, trade-offs
API.md · ASSUMPTIONS.md · requests.http
```

Route handlers only translate HTTP to and from service calls. Every business rule lives in `services/`, and every balance change goes through a single function, `post_entry()`.

## Documentation

- **[API.md](API.md)**: every endpoint with request and response examples, plus the full error-code reference
- **[ASSUMPTIONS.md](ASSUMPTIONS.md)**: every assumption and interpretation of the spec
- **[docs/DESIGN_DECISIONS.md](docs/DESIGN_DECISIONS.md)**: design decisions, alternatives and trade-offs
- Interactive: Swagger UI at `/docs`, ReDoc at `/redoc`

## How this was built

I used [Claude Code](https://claude.com/claude-code) as a pair programmer for the code, tests and documentation. I specified the technical decisions up front: the stack, the schema and constraints, the locking and idempotency strategy, and the error contract. I reviewed and verified every phase before moving on. I understand every decision documented here and can explain the reasoning behind it.
