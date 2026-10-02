# Breaker Concurrency Verification

## Checks

The existing real-HTTP concurrency tests cover:

- Same idempotency key and identical payload: one `201`, seven `200` replays, one row.
- Different keys and the same window: one `201`, seven `409 OVERLAP_CONFLICT` responses, one row.
- Mixed overlapping windows: successful rows remain non-overlapping.

## Initial finding

Repeated execution exposed a genuine intermittent failure in the original three-attempt deadlock retry:

```text
FAILED tests/concurrency/test_concurrency.py::test_different_keys_same_window_concurrent - httpx.ReadTimeout: timed out
psycopg.errors.DeadlockDetected: deadlock detected
DETAIL:  Process 13400 waits for ShareLock on speculative token 8 of transaction 2845; blocked by process 14176.
Process 14176 waits for ShareLock on speculative token 8 of transaction 2846; blocked by process 13400.
```

## Repair

`app/backend/main.py` now takes a transaction-scoped PostgreSQL advisory lock keyed by `table_id` before the reservation insert. The GiST exclusion constraint remains in place and remains the database invariant authority. The bounded deadlock retry remains as additional transient-error handling.

## Verification

Command:

```text
.venv\Scripts\python.exe -m pytest tests/concurrency -q
```

Repeated five-run stress command:

```text
1..5 | ForEach-Object { Write-Output "RUN $_"; .\.venv\Scripts\python.exe -m pytest tests/concurrency -q }
```

Observed:

```text
RUN 1
3 passed in 20.15s
RUN 2
3 passed in 23.56s
RUN 3
3 passed in 21.27s
RUN 4
3 passed in 17.37s
RUN 5
3 passed in 4.35s
```

Result: **PASS**. Fifteen repeated concurrency tests passed with no 500 responses or timeouts after the repair.