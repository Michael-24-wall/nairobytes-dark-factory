"""T5: concurrency against a real uvicorn server (R8, I1, I6).

These tests must fail if the GiST exclusion constraint is dropped or if the
`ON CONFLICT (idempotency_key)` handling is removed.
"""

import concurrent.futures as cf
import threading

import httpx

from api_helpers import (
    all_reservations,
    count_key,
    count_reservations,
    make_payload,
    overlapping_pair_count,
    seed_table,
    uniq,
)

WORKERS = 8


def _post(base_url, payload, barrier=None):
    if barrier is not None:
        barrier.wait()
    with httpx.Client(base_url=base_url, timeout=30) as client:
        r = client.post("/reservations", json=payload)
        try:
            body = r.json()
        except ValueError:
            body = {"raw": r.text}
        return r.status_code, body


def _parallel(base_url, payloads):
    """POST all payloads simultaneously; returns [(status, body), ...]."""
    barrier = threading.Barrier(len(payloads))
    with cf.ThreadPoolExecutor(max_workers=len(payloads)) as pool:
        futures = [pool.submit(_post, base_url, p, barrier) for p in payloads]
        return [f.result() for f in futures]


def test_same_key_identical_payload_concurrent(live_server):
    seed_table()
    payload = make_payload(idempotency_key=uniq("same-key"))

    results = _parallel(live_server, [dict(payload) for _ in range(WORKERS)])

    statuses = [s for s, _ in results]
    assert set(statuses) <= {201, 200}, results
    assert statuses.count(201) == 1, results
    assert statuses.count(200) == WORKERS - 1, results

    ids = {b["reservation_id"] for _, b in results}
    assert len(ids) == 1, results
    assert count_reservations() == 1
    assert count_key(payload["idempotency_key"]) == 1


def test_different_keys_same_window_concurrent(live_server):
    seed_table()
    payloads = [
        make_payload(idempotency_key=uniq("win-key")) for _ in range(WORKERS)
    ]

    results = _parallel(live_server, payloads)

    statuses = [s for s, _ in results]
    assert set(statuses) <= {201, 409}, results
    assert statuses.count(201) == 1, results
    assert statuses.count(409) == WORKERS - 1, results
    errors = [b.get("error") for s, b in results if s == 409]
    assert errors == ["OVERLAP_CONFLICT"] * (WORKERS - 1), results

    assert count_reservations() == 1, "exactly one row may win a window (I6)"
    assert overlapping_pair_count() == 0, "I1 must hold after the race"


def test_mixed_overlapping_load_keeps_i1(live_server):
    seed_table()
    payloads = [
        make_payload(idempotency_key=uniq("mix-key"), start_time=s, end_time=e)
        for s, e in [
            ("2026-06-02T18:00:00+00:00", "2026-06-02T19:00:00+00:00"),
            ("2026-06-02T18:00:00+00:00", "2026-06-02T19:00:00+00:00"),
            ("2026-06-02T18:30:00+00:00", "2026-06-02T19:30:00+00:00"),
            ("2026-06-02T17:30:00+00:00", "2026-06-02T18:30:00+00:00"),
            ("2026-06-02T18:15:00+00:00", "2026-06-02T18:45:00+00:00"),
            ("2026-06-02T21:00:00+00:00", "2026-06-02T22:00:00+00:00"),
            ("2026-06-02T22:00:00+00:00", "2026-06-02T23:00:00+00:00"),
            ("2026-06-02T20:00:00+00:00", "2026-06-02T21:00:00+00:00"),
        ]
    ]

    results = _parallel(live_server, payloads)

    statuses = [s for s, _ in results]
    assert set(statuses) <= {201, 409}, results
    assert statuses.count(201) >= 4, results
    assert count_reservations() == statuses.count(201)
    assert overlapping_pair_count() == 0, "I1: no overlapping active pair"
    rows = all_reservations()
    assert rows, "the race must still persist the winners"
    assert all(r["status"] == "active" for r in rows)


HUNDRED = 100


def test_hundred_parallel_attempts_one_slot_yields_exactly_one_winner(live_server):
    """One table, one bookable slot, 100 simultaneous bookings -> exactly one.

    This is the hackathon acceptance scenario. It is not simulated: 100 threads
    hit a real uvicorn server through real PostgreSQL transactions and the GiST
    exclusion constraint decides the single winner.
    """
    seed_table()
    payloads = [make_payload(idempotency_key=uniq("hundred")) for _ in range(HUNDRED)]
    assert len({p["start_time"] for p in payloads}) == 1  # identical window

    results = _parallel(live_server, payloads)

    statuses = [s for s, _ in results]
    assert set(statuses) <= {201, 409}, results
    assert statuses.count(201) == 1, f"expected exactly one winner, got {statuses.count(201)}"
    assert statuses.count(409) == HUNDRED - 1, results
    assert [b.get("error") for s, b in results if s == 409] == ["OVERLAP_CONFLICT"] * (HUNDRED - 1)

    assert count_reservations() == 1, "100 parallel attempts must persist exactly one row"
    assert overlapping_pair_count() == 0, "I1 must hold after the storm"
    winners = [b for s, b in results if s == 201]
    assert len(winners) == 1 and winners[0]["reservation_id"]
