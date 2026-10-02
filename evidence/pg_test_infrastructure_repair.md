# PostgreSQL Test Infrastructure Repair

## Root cause

The reported `_ensure_db` `NameError` is not present in the current checkout. Inspection of `tests/pg_utils.py` found `_ensure_db()` defined before `ensure_server()` and its two calls: one when the isolated server is already reachable and one after the server start/readiness loop. Importing the helper from `tests/` and calling `ensure_server()` succeeded against PostgreSQL on `127.0.0.1:5439`.

Therefore, the reported error came from an earlier/stale version of `tests/pg_utils.py`; no additional repair to that file was necessary in this checkout. The existing helper safely creates the `reservations` database only when absent, enables `btree_gist`, and is repeatable. Port 5439 and the temporary cluster behavior remain unchanged.

## Files changed

- `app/backend/main.py`
- `evidence/pg_test_infrastructure_repair.md`

`tests/pg_utils.py` was inspected but not changed because the required `_ensure_db()` implementation is already present and functional.

## Exact fixes

- Converted reservation UUIDs to strings before JSON response serialization.
- Normalized `created_at` to UTC before returning it.
- Removed the Pydantic minimum-length constraint from `customer_name` so blank values reach the existing `400 INVALID_CUSTOMER_NAME` validation.
- Retried up to three times with a short backoff when PostgreSQL reports a transient deadlock from concurrent identical-key speculative inserts. Exclusion and foreign-key errors retain their existing responses.

## Commands executed and results

Helper verification:

```text
.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, 'tests'); import pg_utils as p; print(p.__file__); print(p._ensure_db); p.ensure_server(); print('ensure_server ok')"
```

Observed: imported `tests\pg_utils.py`, `_ensure_db` resolved to a function, and `ensure_server ok` printed.

Focused regression suite:

```text
.venv\Scripts\python.exe -m pytest tests/idempotency tests/timezone tests/test_reservations.py tests/concurrency -q
```

Observed: `35 passed, 1 warning`.

Concurrency verification after the deadlock fix:

```text
.venv\Scripts\python.exe -m pytest tests/concurrency/test_concurrency.py -q
```

Observed: `3 passed in 6.23s`.

Required full quiet run, using the project virtual environment:

```text
python -m pytest tests -q
```

Observed after activating `.venv`: `46 passed, 1 warning in 123.04s (0:02:03)`.

Required full verbose run, using the project virtual environment:

```text
python -m pytest tests -vv
```

Observed after activating `.venv`: `46 passed, 1 warning in 92.98s (0:01:32)`.

## Remaining failures

None. The only remaining test output is the existing `StarletteDeprecationWarning` about `httpx` and `starlette.testclient`; it does not fail the suite.