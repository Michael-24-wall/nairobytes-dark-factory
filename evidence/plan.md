# Architect Plan — Restaurant Reservation System (Nairobytes Dark Factory)

Author: Nairobytes Architect (`@michaelwallance4/nairobytes-architect`)
Status: PLAN ONLY — no code was written, changed, or executed by the Architect.
Scope: review of the existing specification + current repository, definition of
requirements/invariants/risks/tasks T1–T6, and handoff to Builder.

## 0. Repository review (observed, not executed)

| Area | File(s) | Observed state |
|---|---|---|
| Schema | `app/backend/schema.sql` | exists: `tables`, `reservations`, `CHECK(end_time > start_time)`, `UNIQUE(idempotency_key)`, FK, GiST `EXCLUDE ... tstzrange(start,end,'[)') WHERE status='active'` |
| DB access | `app/backend/db.py` | psycopg3, `autocommit=True`, `dict_row`, `apply_schema()` |
| API | `app/backend/main.py` | `POST /tables`, `POST /reservations` (insert + `ON CONFLICT (idempotency_key) DO NOTHING` + hash compare), `GET /reservations/{id}` |
| Tests present | `tests/test_schema.py` (6), `tests/test_tables.py` (5) | DB-constraint tests and `/tables` endpoint tests |
| Tests missing | `tests/idempotency/`, `tests/concurrency/`, `tests/timezone/` | **empty directories** (`.gitkeep` only) |
| Tests missing | reservation API | **no test file exercises `POST /reservations` or `GET /reservations/{id}`** |
| Harness | `tests/conftest.py` | local PostgreSQL 18 on `127.0.0.1:5439` (`tests/pg_utils.py`), autouse TRUNCATE between tests, `client` fixture, `live_server` fixture (uvicorn) **currently unused** |
| Evidence | `evidence/*.txt`, `evidence/repair_keyerror.md` | Builder previously reported `11 passed` (schema + tables only) |

Test command: `.venv/Scripts/python.exe -m pytest tests -q` (rootdir has pytest config in `pyproject.toml`).

**Conclusion of review:** schema, table creation, reservation creation, overlap
protection, idempotency and timezone handling are *implemented in code*, but the
T4/T5/T6 behaviours (idempotency, concurrency, timezone) and the reservation
retrieval path have **no automated tests**, so the corresponding invariants are
currently unproven. The Builder's remaining work is coverage + defect repair,
not redesign.

## 1. Requirements (numbered, testable)

- **R1 (schema):** `schema.sql` creates `tables` and `reservations`; a reservation
  stores `customer_name`, `table_id` (FK), `start_time`, `end_time` (`timestamptz`),
  `idempotency_key` (unique), `request_hash`, `status`, `created_at`.
- **R2 (table creation):** `POST /tables` returns `201` with the created row;
  `capacity < 1` → `400 INVALID_CAPACITY`; duplicate `table_id` → `409 TABLE_EXISTS`;
  missing fields → `422`.
- **R3 (reservation creation):** `POST /reservations` with a valid body and an
  existing table returns `201` and a body containing `reservation_id`,
  `start_time`, `end_time` in **UTC offset form** (`...+00:00`/`Z`).
- **R4 (overlap):** a reservation that overlaps an existing *active* reservation of
  the same table is rejected with `409 OVERLAP_CONFLICT`, and no row is persisted.
  Overlap rejection must be enforced by the **database** (GiST exclusion
  constraint), not only by application code.
- **R5 (adjacency):** a reservation whose `start_time ==` an existing
  `end_time` on the same table is accepted (`201`) and both rows persist
  (half-open ranges `[)`).
- **R6 (idempotent replay):** resubmitting a byte-identical payload with the same
  `idempotency_key` returns `200` with the **same** `reservation_id` and does not
  create a second row (`count(*)` unchanged).
- **R7 (key reuse, different payload):** the same `idempotency_key` with a
  different payload (`customer_name`, `table_id`, `start_time`, `end_time`) is
  rejected with `409 IDEMPOTENCY_PAYLOAD_MISMATCH` and the stored reservation is
  unchanged.
- **R8 (concurrency):** N concurrent requests for the same table/window (either
  distinct keys or the same key) executed against a live server result in
  **exactly one** persisted row for that window; losers receive `409` or the
  idempotent `200`, never a second overlapping row.
- **R9 (time validation):** naive timestamps (no offset) → `400 NAIVE_DATETIME`;
  `end_time <= start_time` → `400 INVALID_TIME_RANGE`; blank `customer_name` →
  `400 INVALID_CUSTOMER_NAME`; unknown `table_id` → `404 UNKNOWN_TABLE`.
- **R10 (timezone equivalence):** two requests describing the same instant with
  different offsets (e.g. `2026-06-01T18:00:00+02:00` vs `2026-06-01T16:00:00+00:00`)
  are stored as the same instant; when used as a replay of the same key they are
  treated as identical payloads (R6), and responses always render UTC.
- **R11 (retrieval):** `GET /reservations/{id}` returns `200` with the stored
  reservation (UTC-normalized timestamps); unknown or malformed id → `404 NOT_FOUND`;
  a reservation created through the API is retrievable and matches what was created.
- **R12 (evidence):** every requirement above has an automated test that is
  actually executed; results are written to `evidence/`. Human acceptance is the
  final authority; nothing is claimed without execution.

## 2. Architecture

```
client ──HTTP──> FastAPI (app/backend/main.py)
                   │  validation R9/R10, request_hash (sha256 of normalized payload)
                   ▼
             psycopg3 connection (autocommit, dict_row)  app/backend/db.py
                   ▼
             PostgreSQL 18  (schema.sql)
                 tables(reservation_id uuid PK, ..., UNIQUE(idempotency_key),
                        CHECK(end_time > start_time), FK table_id)
                 EXCLUDE USING gist (table_id WITH =,
                        tstzrange(start_time, end_time, '[)') WITH &&)
                        WHERE status = 'active'
```

- **Data model:** `timestamptz` stores instants; the API normalizes to UTC
  (`astimezone(timezone.utc)`) before insert and before rendering, so offset
  variants collapse to one instant.
- **Idempotency:** `request_hash = sha256(strip(customer_name), table_id,
  normalized start, normalized end)`; unique index on `idempotency_key` +
  `ON CONFLICT DO NOTHING`; on no-insert the stored hash decides `200 replay`
  vs `409 IDEMPOTENCY_PAYLOAD_MISMATCH`.
- **Invariant enforcement point:** overlap and adjacency are decided **only** by
  the GiST exclusion constraint (`[)` ranges ⇒ adjacency allowed), so any
  application/threading bug cannot persist overlapping rows.
- **Concurrency:** sync endpoints run in the ASGI threadpool against a live
  uvicorn server (`live_server` fixture); each request owns its own autocommit
  connection, so the database serializes conflicting inserts.

## 3. Invariants (each must be checkable by a test)

- **I1:** For every pair of `active` rows with the same `table_id`,
  their half-open ranges do not intersect: `NOT (a.start < b.end AND b.start < a.end)`.
- **I2:** `end_time > start_time` for every persisted row (DB `CHECK`).
- **I3:** `count(reservations where idempotency_key = K) <= 1` for all `K`
  (DB `UNIQUE`).
- **I4:** Replaying an identical request with key `K` yields the same
  `reservation_id` and does not change `count(*)`.
- **I5:** A different payload under an existing key `K` changes nothing and is
  rejected.
- **I6:** Under concurrent load, `count` of rows overlapping a given window for a
  given table is exactly `1` (I1 holds globally afterwards).
- **I7:** Adjacent reservations (`a.end == b.start`) are both persisted for the
  same table.
- **I8:** All timestamps leaving the API are UTC-offset normalized; naive input
  never reaches the database through the API.
- **I9:** Human acceptance is final: no test result may be claimed without the
  command having been run and recorded under `evidence/`.

## 4. Risks

1. **Exclusion-violation vs idempotency ordering (highest).** For a *replay* of an
   existing key, the inserted tuple overlaps its own stored row, so the request
   may raise `ExclusionViolation` **before** the `ON CONFLICT (idempotency_key)`
   path runs, turning a correct replay into `409 OVERLAP_CONFLICT` (R6 broken).
   The API must distinguish "conflict because the same key already exists" from a
   genuine overlap (e.g. on `ExclusionViolation`, re-check whether the key exists
   and the hash matches, then serve the replay). **Builder must add a test for
   replay; Breaker must attack exactly this ordering.**
2. **Race between `DO NOTHING` and the follow-up `SELECT`.** Under read-committed
   this is normally safe (the conflicting insert waits for the winner to commit),
   but the follow-up lookup must run in a *new statement* (it does). Verify under
   real concurrency, not only with `TestClient`.
3. **Timezone handling.** Pydantic parses offset-bearing strings; naive strings
   must be rejected *before* `_normalize()` (which would silently apply the
   server-local zone). Offset-equivalent payloads must hash identically, or R10
   breaks idempotency.
4. **Test isolation.** Autouse `TRUNCATE` between tests plus a session-scoped
   schema; concurrency tests must not assume empty tables mid-test and must not
   share idempotency keys across tests.
5. **Partial failure / resource handling.** `session()` closes the connection in
   `finally`; an exception inside a request must not leave a transaction open or a
   row half-written (autocommit ⇒ single-statement atomicity).
6. **Data integrity shortcuts.** Tests must not be weakened, skipped, or marked
   `xfail` to get green results; no test may delete the exclusion constraint.
7. **Evidence integrity.** Evidence files must contain real command output with
   timestamps; claims in messages must match the files under `evidence/`.

## 5. Tasks (ordered, each with an acceptance test)

- **T1 — Schema verification (extend existing).**
  Acceptance: `tests/test_schema.py` proves I1 (overlap rejected), I2 (end <= start
  rejected), I3 (duplicate key rejected), I7 (adjacent accepted), FK rejection,
  capacity `CHECK`. Mostly present; keep green.

- **T2 — Table creation (extend existing).**
  Acceptance: `tests/test_tables.py` proves R2 (201/400/409/422). Present; keep green.

- **T3 — Reservation creation + overlap protection (NEW tests).**
  Add `tests/test_reservations.py` covering: R3 success shape, R4 `409
  OVERLAP_CONFLICT` with DB row count unchanged, R5 adjacency via API `201`,
  R9 `400/404` validations, partial overlap/contained/identical-window cases.

- **T4 — Idempotency (NEW tests in `tests/idempotency/`).**
  Add tests for R6 (replay → `200`, same `reservation_id`, `count(*) == 1`,
  including a replay whose times use a *different offset* for the same instant),
  R7 (`409 IDEMPOTENCY_PAYLOAD_MISMATCH`, stored row unchanged), and distinct keys
  creating distinct rows. Include the risk-#1 ordering case (replay of the exact
  same key/window). Fix `app/backend/main.py` if a defect surfaces (root cause).

- **T5 — Concurrency (NEW tests in `tests/concurrency/`).**
  Use the existing `live_server` fixture with a real HTTP client and ≥8 parallel
  workers: (a) same key + identical payload ⇒ exactly 1 row, responses ∈ {201,200};
  (b) different keys + same window ⇒ exactly 1 row, others `409`; (c) mixed
  overlapping windows ⇒ I1 holds (`SELECT` self-join finds no overlapping pair).
  Acceptance: tests fail if the exclusion constraint or the conflict handling is
  removed.

- **T6 — Retrieval + timezone/offset (NEW tests in `tests/timezone/` plus GET
  coverage).**
  Acceptance: R9 naive → `400 NAIVE_DATETIME`; `+02:00` vs `+00:00` same-instant
  requests behave per R10; created reservation retrievable per R11; unknown id →
  `404`; API output timestamps carry a UTC offset.

- **T7 — Evidence & handoff (Builder).**
  Run the full suite, capture verbatim output under `evidence/`
  (`builder_test_run_full.txt`), state pass/fail counts honestly, then hand off to
  Breaker. If a defect is found, repair root cause without weakening tests and
  record `evidence/repair_<defect>.md`.

## 6. Explicit non-goals

- No redesign of schema, endpoints, or stack.
- No new product requirements (no auth, no payment, no seat-count optimization).
- No claim of success by the Architect: this document is a plan only.

## 7. Round-2 review addendum (re-inspection of the repository, not executed)

Files observed since round 1 (Builder progress):

| Task | File | Observed coverage |
|---|---|---|
| T3 | `tests/test_reservations.py` (172 lines, 12 tests + 5 parametrized) | R3 shape, R4 overlap incl. partial/contained/identical/covers + row-count check, R5 adjacency, R9 naive/end<=start/blank/unknown-table/422, other-table allowed |
| T4 | `tests/idempotency/test_idempotency.py` (149 lines, 9 tests) | R6 replay (incl. the risk-#1 same-window replay), R7 mismatch with stored-row-unchanged (name, overlapping window, disjoint window), R10 offset-equivalent replay, R3 distinct keys, I3 |
| T6 | `tests/timezone/test_timezone.py` (107 lines, 8 tests) | R9 naive rejection, R10 offset equivalence + negative offset, R11 GET 200/404/malformed, UTC-offset rendering |
| helpers | `tests/api_helpers.py` | `seed_table`, `make_payload`, `count_reservations`, `count_key`, `overlapping_pair_count` (I1 self-join), `fetch_reservation` |
| T5 | `tests/concurrency/` | **still empty (`.gitkeep` only) — the `live_server` fixture is still unused** |

Still outstanding before handoff to Breaker:

1. **T5 is unbuilt.** No test exercises concurrent requests. Required acceptance
   per plan §5: ≥8 parallel workers against `live_server`; (a) same key + identical
   payload ⇒ exactly 1 row, statuses ∈ {201,200}; (b) different keys + same window
   ⇒ exactly 1 row, losers `409 OVERLAP_CONFLICT`; (c) `overlapping_pair_count() == 0`
   after mixed load (I1). The helper for (c) already exists.
2. **No current full-suite evidence.** `evidence/` contains only the pre-round-1
   `11 passed` runs; the new T3/T4/T6 tests have no recorded execution output.
   Required: verbatim `.venv/Scripts/python.exe -m pytest tests -q` output saved to
   `evidence/builder_test_run_full.txt`, with honest pass/fail counts.
3. **Expected-failure case to resolve honestly:** `tests/timezone/test_timezone.py::test_offset_equivalent_instants_normalize_identically`
   posts two *different-key* payloads for the identical window on one table and
   asserts `201` + `count_reservations() == 2`, which contradicts invariant I1/R4
   (the second insert must be `409 OVERLAP_CONFLICT`). Architect assessment: this
   is a **test-authoring defect, not a product requirement** — the same-instant
   equivalence claim (R10) is already proven by
   `tests/idempotency/test_idempotency.py::test_replay_offset_equivalent_same_instant_is_identical_payload`.
   Builder must correct the timezone test to state a *non-contradictory* fact
   (e.g. different table, or assert both normalize to the same UTC instants via
   two tables / assert 409 for the second). **Do not** weaken I1, delete the
   exclusion constraint, or mark the test `xfail`/skip to make it green.
4. Repair any genuine product defect surfaced by the run at the root cause, with
   `evidence/repair_<defect>.md`, then re-run the full suite.

When 1–4 are done, hand off to `@michaelwallance4/nairobytes-breaker` with real
counts and file paths.
