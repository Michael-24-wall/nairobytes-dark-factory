# Final Verification

## Result

**PASS**, after repairing one genuine concurrency defect found by repeated breaker stress.

## Implementation verified

- PostgreSQL test infrastructure remains isolated on port `5439`.
- The GiST exclusion constraint enforces no overlapping active reservations.
- Adjacent half-open reservations remain allowed.
- Idempotency uses the unique key and normalized request hash.
- Reservation writes now use a transaction-scoped advisory lock keyed by table to prevent speculative-insert deadlocks under concurrent contention. The database exclusion constraint remains authoritative.

## Results

- Concurrency: 3 tests passed in each of 5 repeated runs, 15/15 total.
- Idempotency: 8 passed.
- Timezones: 8 passed.
- Database schema constraints: 6 passed.
- Combined adversarial/schema slice: 25 passed.
- Final quiet regression: 46 passed, 1 warning.
- Final verbose regression: 46 passed, 1 warning.
- Direct database check: `overlapping_pair_count= 0`.

## Defect and repair

Repeated concurrent different-key, same-window requests could deadlock in PostgreSQL's speculative insert/exclusion-constraint path. The prior bounded retry was insufficient under stress and could produce HTTP 500 or timeout. The root repair was to serialize writes per table with `pg_advisory_xact_lock`; the existing retry remains as defense for transient deadlocks.

## Known test correction

The equivalent-timezone test uses different tables. A separate test proves that equivalent instants on the same table are rejected as overlap. This preserves I1 while testing I6.

## Evidence files

- `evidence/breaker_concurrency.md`
- `evidence/breaker_idempotency.md`
- `evidence/breaker_timezone.md`
- `evidence/final_test_run.txt`
- `evidence/final_verification.md`

## Remaining warnings and limitations

The only remaining warning is the non-failing `StarletteDeprecationWarning` concerning `httpx` and `starlette.testclient`. No invariant remains unverified by the executed checks.