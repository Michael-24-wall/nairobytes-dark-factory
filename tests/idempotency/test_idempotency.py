"""T4: idempotent replay, key reuse with a different payload (R6, R7, R10)."""

from datetime import timezone

from api_helpers import (
    count_key,
    count_reservations,
    fetch_reservation,
    make_payload,
    seed_table,
)


def _utc(dt) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _create(client, body):
    r = client.post("/reservations", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_replay_identical_payload_200_same_id_one_row(client):
    """Risk #1: the replay window equals the stored window, so the new tuple
    overlaps its own row — the exclusion constraint must not turn the replay
    into 409 OVERLAP_CONFLICT."""
    seed_table()
    body = make_payload()
    first = _create(client, body)

    replay = client.post("/reservations", json=body)
    assert replay.status_code == 200, replay.text
    assert replay.json()["reservation_id"] == first["reservation_id"]
    assert count_reservations() == 1
    assert count_key(body["idempotency_key"]) == 1


def test_replay_twice_still_one_row(client):
    seed_table()
    body = make_payload()
    first = _create(client, body)
    for _ in range(2):
        r = client.post("/reservations", json=body)
        assert r.status_code == 200, r.text
        assert r.json()["reservation_id"] == first["reservation_id"]
    assert count_reservations() == 1


def test_replay_offset_equivalent_same_instant_is_identical_payload(client):
    """R10: `18:00+00:00` and `20:00+02:00` are the same instant, so the
    replayed payload must hash identically and return the same reservation."""
    seed_table()
    utc_body = make_payload(
        start_time="2026-06-01T18:00:00+00:00",
        end_time="2026-06-01T19:00:00+00:00",
    )
    first = _create(client, utc_body)

    offset_body = dict(utc_body)
    offset_body["start_time"] = "2026-06-01T20:00:00+02:00"
    offset_body["end_time"] = "2026-06-01T21:00:00+02:00"

    r = client.post("/reservations", json=offset_body)
    assert r.status_code == 200, r.text
    assert r.json()["reservation_id"] == first["reservation_id"]
    assert r.json()["start_time"] == "2026-06-01T18:00:00+00:00"
    assert count_reservations() == 1
    assert count_key(utc_body["idempotency_key"]) == 1


def test_same_key_different_name_409_mismatch_row_unchanged(client):
    seed_table()
    body = make_payload()
    first = _create(client, body)
    stored_before = fetch_reservation(first["reservation_id"])

    other = dict(body)
    other["customer_name"] = "Bob"
    r = client.post("/reservations", json=other)
    assert r.status_code == 409, r.text
    assert r.json()["error"] == "IDEMPOTENCY_PAYLOAD_MISMATCH"

    stored_after = fetch_reservation(first["reservation_id"])
    assert stored_before == stored_after
    assert stored_after["customer_name"] == "Alice"
    assert count_reservations() == 1
    assert count_key(body["idempotency_key"]) == 1


def test_same_key_different_window_overlapping_409_mismatch(client):
    """Same key, different (overlapping) window: the mismatch error must win
    over OVERLAP_CONFLICT and the stored row must not move."""
    seed_table()
    body = make_payload()
    first = _create(client, body)

    other = dict(body)
    other["start_time"] = "2026-06-01T18:30:00+00:00"
    other["end_time"] = "2026-06-01T19:30:00+00:00"
    r = client.post("/reservations", json=other)
    assert r.status_code == 409, r.text
    assert r.json()["error"] == "IDEMPOTENCY_PAYLOAD_MISMATCH"

    stored = fetch_reservation(first["reservation_id"])
    assert _utc(stored["start_time"]) == "2026-06-01T18:00:00+00:00"
    assert _utc(stored["end_time"]) == "2026-06-01T19:00:00+00:00"
    assert count_reservations() == 1


def test_same_key_different_disjoint_window_409_mismatch(client):
    seed_table()
    body = make_payload()
    first = _create(client, body)

    other = dict(body)
    other["start_time"] = "2026-06-01T21:00:00+00:00"
    other["end_time"] = "2026-06-01T22:00:00+00:00"
    r = client.post("/reservations", json=other)
    assert r.status_code == 409, r.text
    assert r.json()["error"] == "IDEMPOTENCY_PAYLOAD_MISMATCH"

    stored = fetch_reservation(first["reservation_id"])
    assert _utc(stored["start_time"]) == "2026-06-01T18:00:00+00:00"
    assert _utc(stored["end_time"]) == "2026-06-01T19:00:00+00:00"
    assert count_reservations() == 1


def test_distinct_keys_create_distinct_rows(client):
    seed_table()
    first = _create(client, make_payload())
    second = _create(
        client,
        make_payload(
            start_time="2026-06-01T20:00:00+00:00",
            end_time="2026-06-01T21:00:00+00:00",
        ),
    )
    assert first["reservation_id"] != second["reservation_id"]
    assert count_reservations() == 2


def test_unique_key_invariant_i3(client):
    seed_table()
    body = make_payload()
    _create(client, body)
    for _ in range(3):
        client.post("/reservations", json=body)
    assert count_key(body["idempotency_key"]) == 1
