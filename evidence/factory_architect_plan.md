# Factory Architect Plan

## Components

- `app/backend/main.py`: FastAPI endpoints, input validation, UTC normalization, request hashing, idempotent insert/replay handling, and per-table transaction-scoped advisory locking.
- `app/backend/db.py`: psycopg3 connection/session management against the configured PostgreSQL test database.
- `app/backend/schema.sql`: tables, foreign key, checks, unique idempotency key, and GiST exclusion constraint.
- `tests/`: API, schema, idempotency, concurrency, and timezone verification.

## Checkable invariants

1. Active reservations for one table never overlap.
2. Adjacent half-open reservations are accepted.
3. Identical replay returns the original reservation and creates no row.
4. Reusing a key with a different payload returns `IDEMPOTENCY_PAYLOAD_MISMATCH` and leaves storage unchanged.
5. Concurrent requests cannot create overlapping rows or duplicate idempotent rows.
6. Offset-equivalent timestamps hash and render consistently in UTC.

## Execution plan

1. Builder runs the complete test suite and inspects implementation/schema.
2. Breaker independently runs concurrency, idempotency, timezone, adjacency, retry, and database-invariant attacks without changing application code.
3. Repair is performed only for a reproducible genuine defect, followed by a focused retest and full suite.
4. Verifier reruns the full suite, checks evidence, and records any warnings or unverified items.
5. Human acceptance remains the final decision.