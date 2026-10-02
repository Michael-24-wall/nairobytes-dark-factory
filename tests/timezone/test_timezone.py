"""T6: retrieval (R11) and timezone/offset handling (R8, R10)."""

import uuid

from api_helpers import (
    count_reservations,
    make_payload,
    overlapping_pair_count,
    seed_table,
)

UTC_START = "2026-06-01T18:00:00+00:00"
UTC_END = "2026-06-01T19:00:00+00:00"


def _create(client, body=None):
    seed_table()
    body = body or make_payload()
    r = client.post("/reservations", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_naive_input_rejected_before_normalize(client):
    """A naive string must be rejected, never silently shifted into the
    server-local zone by `_normalize()`."""
    seed_table()
    r = client.post(
        "/reservations",
        json=make_payload(start_time="2026-06-01T18:00:00", end_time=UTC_END),
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"] == "NAIVE_DATETIME"
    assert count_reservations() == 0

    r = client.post(
        "/reservations",
        json=make_payload(start_time=UTC_START, end_time="2026-06-01T19:00:00"),
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"] == "NAIVE_DATETIME"
    assert count_reservations() == 0


def test_offset_equivalent_instants_normalize_identically(client):
    """Same instant written with two different offsets must render as the same
    UTC timestamps. The two payloads use *different* tables so that I1/R4
    (no overlapping active pair per table) is not contradicted."""
    seed_table("t1")
    seed_table("t2")
    utc_body = make_payload(table_id="t1", start_time=UTC_START, end_time=UTC_END)
    offset_body = make_payload(
        table_id="t2",
        start_time="2026-06-01T20:00:00+02:00",
        end_time="2026-06-01T21:00:00+02:00",
    )
    a = client.post("/reservations", json=utc_body)
    b = client.post("/reservations", json=offset_body)
    assert a.status_code == 201, a.text
    assert b.status_code == 201, b.text
    assert a.json()["start_time"] == UTC_START
    assert a.json()["end_time"] == UTC_END
    assert b.json()["start_time"] == UTC_START
    assert b.json()["end_time"] == UTC_END
    assert count_reservations() == 2


def test_offset_equivalent_same_table_second_is_overlap_conflict(client):
    """Complementary guard: on the SAME table the two offset-equivalent
    payloads describe one window, so the second insert must be rejected by
    I1/R4 rather than silently accepted."""
    seed_table()
    a = client.post(
        "/reservations",
        json=make_payload(start_time=UTC_START, end_time=UTC_END),
    )
    b = client.post(
        "/reservations",
        json=make_payload(
            start_time="2026-06-01T20:00:00+02:00",
            end_time="2026-06-01T21:00:00+02:00",
        ),
    )
    assert a.status_code == 201, a.text
    assert b.status_code == 409, b.text
    assert b.json()["error"] == "OVERLAP_CONFLICT"
    assert count_reservations() == 1
    assert overlapping_pair_count() == 0


def test_negative_offset_instant_normalizes_to_utc(client):
    created = _create(
        client,
        make_payload(start_time="2026-06-01T13:00:00-05:00", end_time="2026-06-01T14:00:00-05:00"),
    )
    assert created["start_time"] == UTC_START
    assert created["end_time"] == UTC_END


def test_get_reservation_200_matches_creation(client):
    created = _create(client)
    r = client.get(f"/reservations/{created['reservation_id']}")
    assert r.status_code == 200, r.text
    data = r.json()
    for field in (
        "reservation_id",
        "customer_name",
        "table_id",
        "start_time",
        "end_time",
        "idempotency_key",
        "status",
        "created_at",
    ):
        assert data[field] == created[field], field
    assert "request_hash" not in data


def test_get_unknown_id_404(client):
    seed_table()
    missing = str(uuid.uuid4())
    r = client.get(f"/reservations/{missing}")
    assert r.status_code == 404, r.text
    assert r.json()["error"] == "NOT_FOUND"


def test_get_malformed_id_404(client):
    seed_table()
    for bad in ("not-a-uuid", "123", "00000000-0000-0000-0000-000000000000"):
        r = client.get(f"/reservations/{bad}")
        assert r.status_code == 404, r.text
        assert r.json()["error"] == "NOT_FOUND"


def test_all_returned_timestamps_carry_utc_offset(client):
    created = _create(client)
    for payload in (created, client.get(f"/reservations/{created['reservation_id']}").json()):
        for field in ("start_time", "end_time", "created_at"):
            value = payload[field]
            assert value.endswith("+00:00") or value.endswith("Z"), (field, value)
