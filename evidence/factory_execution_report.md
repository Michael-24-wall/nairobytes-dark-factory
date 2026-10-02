# Factory Execution Report

## ARCHITECT

Inspected the backend implementation, schema, tests, evidence, and factory mandates. The current design uses PostgreSQL `timestamptz`, a GiST exclusion constraint with half-open ranges, a unique idempotency key, normalized request hashing, and a transaction-scoped advisory lock per table. The execution plan is recorded in `evidence/factory_architect_plan.md`.

Result: **PASS**.

## BUILDER

Command:

```text
.venv\Scripts\python.exe -m pytest tests -q
```

Observed: `46 passed, 1 warning in 56.66s (0:00:56)`.

Implementation and schema inspection confirmed database-enforced overlap, adjacency support, unique idempotency, UTC normalization, and advisory-lock concurrency protection.

Result: **PASS**.

## BREAKER

Command:

```text
.venv\Scripts\python.exe -m pytest tests/concurrency tests/idempotency tests/timezone tests/test_schema.py -q
```

Observed: `25 passed, 1 warning in 145.74s (0:02:25)`.

Repeated attack command:

```text
1..3 | ForEach-Object { Write-Output "BREAKER_CONCURRENCY_RUN $_"; .\.venv\Scripts\python.exe -m pytest tests/concurrency -q }
```

Observed: three runs, each `3 passed` (`6.50s`, `6.56s`, and `6.13s`). The attacks covered same-key concurrency, different-key overlapping windows, mixed overlaps, replay, conflicting keys, adjacency, timezone equivalence, and schema constraints.

Post-attack database query:

```text
overlapping_pair_count= 0
reservation_rows= 4
```

No new application defect was found. The earlier advisory-lock repair remains present and held under these attacks.

Result: **PASS**.

## REPAIR

No repair was required during this factory simulation. The advisory-lock repair was part of the current baseline and was preserved.

Result: **NOT REQUIRED**.

## BREAKER RETEST

Not required as a separate stage because Breaker found no new defect. The Breaker attacks themselves included three repeated concurrency runs against the repaired baseline.

Result: **NOT REQUIRED**.

## VERIFIER

Command:

```text
.venv\Scripts\python.exe -m pytest tests -q
```

Observed: `46 passed, 1 warning in 24.51s`.

Result: **PASS**.

## HUMAN ACCEPTANCE

Human acceptance remains pending and is not something automated execution can establish.