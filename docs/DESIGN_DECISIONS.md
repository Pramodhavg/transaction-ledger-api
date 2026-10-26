# Design Decisions

Each entry gives the decision, why it was made, and what was considered instead. Sections are in rough order of importance.

## 1. Concurrency and atomicity

### Pessimistic row lock per account (`SELECT … FOR UPDATE`)
**Decision.** Every write locks the account row first, then checks duplicates and the balance, then writes the ledger entry and the new balance, then commits. All of this happens in one DB transaction ([transaction_service.py](../app/services/transaction_service.py)).

**Why.** Without a lock, two debits can both read a balance of 100 and both write 90, so one debit silently disappears (a *lost update*). Two debits of 60 against 100 could both pass the balance check, giving an *overdraft*. With the lock, concurrent requests for the **same** account take turns, while requests for different accounts never block each other. The lock lives in Postgres, so it holds with any number of API workers or instances. An in-process mutex would only protect one process.

**Alternatives.**
- **Optimistic locking (a version column with retry):** under contention on a busy account, most attempts fail and retry.
- **`SERIALIZABLE` isolation:** correct, but every write path needs a retry loop for serialization failures.
- **A single conditional `UPDATE … SET balance = balance - :x WHERE balance >= :x`:** lock-free and fast, but it can't cleanly combine the duplicate check and the `balance_after` snapshot in one statement.

**Evidence.**
- 20 simultaneous debits of 10 against 100 give exactly 10 successes, a final balance of 0, and `balance_after` values of exactly 90, 80, …, 0.
- With `FOR UPDATE` removed, 4 of 5 concurrency tests fail and the reconciliation check reports lost updates.

### Deadlock-free transfers: lock both accounts in sorted order
**Decision.** A transfer locks both accounts in ascending id order, whichever direction the money moves ([transfer_service.py](../app/services/transfer_service.py)).

**Why.** Suppose A→B locks A and then wants B, while B→A has locked B and wants A. Each waits for the other forever (Postgres detects this after about 1 second and kills one of them). If every transaction acquires locks in the same global order, a waiting cycle can't form.

**Evidence.** 40 opposite transfers running at once complete with no deadlocks, and money is conserved. With the sort removed, Postgres raises a real `DeadlockDetected` in that test.

### One database transaction per operation
**Decision.** The service wraps all of its work in `with db.begin():`. The ledger entry and balance update (and, for a transfer, the transfer row plus both legs) commit together, and any exception rolls everything back.

**Why.** The spec requires that the transaction and the balance update persist together or not at all, and that partial transfers are impossible. A transaction boundary is the simplest correct way to guarantee that. Tests inject failures after the ledger insert and on a transfer's credit leg, and confirm that nothing persists.

### A single function changes balances: `post_entry()`
**Decision.** Normal transactions and both transfer legs go through the same function, which checks the balance, inserts the entry with `balance_after`, and updates the balance.

**Why.** One place for the balance rules means transfers can't drift from normal transactions. The insufficient-balance and balance-limit rules apply identically everywhere.

## 2. Integrity enforced by the database

### Constraints as a backstop for the code
**Decision.** The schema itself enforces the rules: `CHECK (balance >= 0)`, `CHECK (amount > 0)`, `CHECK (type IN ('credit','debit'))`, `CHECK (balance_after >= 0)`, `CHECK (from_account_id <> to_account_id)`, `UNIQUE (account_id, reference_id)`, `UNIQUE (from_account_id, reference_id)`, and foreign keys with `ON DELETE RESTRICT`.

**Why.** Application checks give friendly errors. Constraints guarantee correctness even if a future code path, a migration script or a manual SQL fix gets it wrong. When a duplicate somehow slips past the in-code check, the `IntegrityError` on the named unique constraint is caught and turned into the same `409`. With the row lock removed in the sabotage experiment, the duplicate-reference test still passed purely because of this constraint.

### Immutability trigger
**Decision.** A PL/pgSQL trigger raises an error on any `UPDATE` or `DELETE` of `transactions` and `transfers` ([migration 0001](../alembic/versions/0001_initial_schema.py)).

**Why.** Having no edit or delete endpoints is necessary but not sufficient, because nothing stops a script or an engineer from running SQL. The trigger makes the ledger append-only at the database level. Corrections are made with new compensating entries, as in accounting. In production, the app's database role would also lack `UPDATE`, `DELETE` and `TRUNCATE` on these tables (defense in depth).

### `VARCHAR` + `CHECK` instead of a Postgres `ENUM`
**Why.** It is equally safe, easier to evolve (adding a value is a one-line constraint change), and simpler in migrations.

### Hand-written Alembic migration with named constraints
**Why.** Autogenerate can't produce triggers, and explicit constraint names let the code recognise which constraint a database error came from. The test suite runs the migration down and then up at the start of every run, so both directions are exercised.

## 3. Money

### `NUMERIC(18,2)` + `Decimal`, never float
**Why.** In binary floating point `0.1 + 0.2 ≠ 0.3`. Money must be exact. Amounts with more than 2 decimals are **rejected, not rounded**, because silently changing an amount is worse than refusing it.

### Money returned as strings (`"150.00"`)
**Why.** JSON numbers are parsed as 64-bit floats by JavaScript and many other clients, so large or precise amounts can silently change. Strings preserve the exact value. Payment APIs use strings or integer minor units for the same reason.

### A clean `422` at the storage limit
**Decision.** A credit that would exceed `9,999,999,999,999,999.99` (the `NUMERIC(18,2)` maximum) returns `422 BALANCE_LIMIT_EXCEEDED`. The code checks this first, and a Postgres numeric overflow (SQLSTATE `22003`) is mapped to the same error as a backstop.

**Why.** A storage limit should never surface as a `500`. A test disables the code check to prove that the database backstop also returns `422`.

## 4. Idempotency

### `reference_id` unique per account, duplicates return `409` with the original
**Why.** If a client times out, it can't know whether its request succeeded. With a reference id, it can safely retry: the second attempt changes nothing and returns the original transaction, so the client learns the outcome. This prevents double charges.

**Details.**
- The duplicate check runs before the balance check, so retrying a successful debit says "already done", not "insufficient balance".
- Rejected requests are not stored, so their reference stays usable.
- Transfer legs use generated `transfer:<id>:debit|credit` references under a prefix clients can't use, so they can never collide with client references.

## 5. Ordering and pagination

### `created_at` from `clock_timestamp()`, not `now()`
**Why.** `now()` returns the time the *database transaction started*. A request that waited for the row lock could then get an *earlier* timestamp than the request it waited for, so "latest first" would disagree with the actual order of balance changes. `clock_timestamp()` is evaluated at insert time, after the lock is held. A concurrency test checks that history order matches the `balance_after` chain under contention.

### `ORDER BY created_at DESC, id DESC` plus a matching index
**Why.**
- Without the `id` tiebreaker, rows with equal timestamps could swap order between page requests, so a row could repeat or go missing.
- The index `(account_id, created_at DESC, id DESC)` lets Postgres read rows already in order and stop after `limit`. `EXPLAIN` confirms the index can serve the query with no separate sort step.

### Offset pagination, count and page from one snapshot
**Why.** The spec asks for total records and total pages, which offset pagination provides naturally. Both queries run in one `REPEATABLE READ` snapshot, so the metadata always agrees with the data returned. For very large histories, keyset (cursor) pagination on the same index is the upgrade path.

### Strict parameters
**Why.** Out-of-range `page` and `limit` return `400` instead of being silently clamped. A page past the end returns an empty list with correct metadata. An unknown account returns `404`, not an empty history.

## 6. API contract and errors

### One error shape everywhere
**Decision.** `{"error": {"code", "message", "details"}}` for application errors, request validation, unknown routes (`404`), wrong methods (`405`, with an accurate `Allow` header) and unexpected exceptions (`500`).

**Why.** A client should never need to parse two error formats. `code` is stable and machine-readable, and `message` is for people. A `500` never includes stack traces or SQL: those go to the server log, so internals aren't exposed to attackers.

### `400` for invalid input, `422` for business rules
**Why.** FastAPI's default `422` for validation errors is replaced. Now `400` always means "fix your request" and `422` always means "valid request, refused by a rule" (insufficient balance, balance limit). Validation errors get specific codes per field (`INVALID_AMOUNT`, `INVALID_TRANSACTION_TYPE`, …), falling back to `VALIDATION_ERROR` when several fields are wrong.

### `extra="forbid"` on every request body
**Why.** A client trying to set `balance`, `balance_after` or `created_at` gets an explicit error instead of being silently ignored, which would hide its bug.

### Swagger that matches reality
**Decision.**
- FastAPI's auto-generated "422 Validation Error" entries are removed.
- Every route documents its real error codes, with examples that name its own fields.
- Business-error examples are built from the actual exception classes, so the docs can't drift from the API.
- Response models have realistic example values.

## 7. Structure

### Thin routes, business logic in services
**Why.** Routes only translate HTTP to and from service calls. Services hold every rule and own their transaction boundaries, so the rules can be reused (transfers reuse `post_entry`) and tested without HTTP (the concurrency tests call the services directly from threads).

### Sync SQLAlchemy 2.0
**Why.** The requests are short and bound by the database. FastAPI runs sync endpoints in a thread pool, and async would add complexity with no correctness benefit here.

## 8. Testing

**Decisions.**
- **Real Postgres, never SQLite.** Locks, triggers, CHECK constraints and `NUMERIC` behaviour only exist in the real engine.
- **Reconciliation after every test.** Every balance must equal Σ credits − Σ debits and the latest `balance_after`, and every transfer must have exactly two legs. A bug anywhere fails the test that caused it.
- **Concurrency tests use real threads**, each with its own connection, released together by a barrier, with timeouts so a hang becomes a failure.
- **The suite refuses to run against the application database.**

**Proof that the tests catch real bugs.** Removing `FOR UPDATE` fails 4 of 5 concurrency tests. Unsorted lock order triggers a real `DeadlockDetected`.

## 9. Operations

- **One-command startup.** Compose healthcheck uses `pg_isready -h 127.0.0.1`, which checks over TCP. On first boot Postgres runs a temporary socket-only server, and a socket probe would report "ready" too early. Migrations run before uvicorn starts.
- **Postgres port not published to the host**, so it can't clash with a local Postgres.
- **Non-root container user. `exec uvicorn`**, so the server receives stop signals directly.
- **`.gitattributes` forces LF line endings**, so a Windows checkout behaves the same inside Linux containers.

## What I would do next

| Area | Next step |
|---|---|
| Security | Authentication and per-account authorization; least-privilege DB role without `UPDATE`/`DELETE`/`TRUNCATE` on ledger tables |
| Migrations | Run as a separate release step instead of on startup, so several replicas never migrate at once |
| Scale | Keyset pagination for long histories; partition `transactions` by time if it grows very large |
| Auditing | A separate log of rejected attempts (who tried what, and why it failed) |
| Idempotency | Store a request fingerprint and return a different error when a reused reference comes with a different payload |
| Integration | Publish ledger events with a transactional outbox, so other services learn about transfers reliably |
| Observability | Structured logs with request ids, metrics for lock wait time and rejection rates |
| Money | Multi-currency with an explicit currency per account and integer minor units |
