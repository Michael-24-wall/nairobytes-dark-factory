"""T3: reservation creation, overlap protection, and validation (R3-R5, R9)."""

import pytest

from api_helpers import count_key, count_reservations, make_payload, seed_table


def _create(client, body):
    r = client.post("/reservations", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_reservation_201_shape(client):
    seed_table()
    body = make_payload()
    r = client.post("/reservations", json=body)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["reservation_id"]
    assert data["customer_name"] == "Alice"
    assert data["table_id"] == "t1"
    assert data["start_time"] == "2026-06-01T18:00:00+00:00"
    assert data["end_time"] == "2026-06-01T19:00:00+00:00"
    assert data["idempotency_key"] == body["idempotency_key"]
    assert data["status"] == "active"
    assert data["start_time"].endswith("+00:00")
    assert data["end_time"].endswith("+00:00")
    assert data["created_at"].endswith("+00:00")
    assert "request_hash" not in data
    assert count_reservations() == 1


def test_overlap_conflict_409_and_no_row_persisted(client):
    seed_table()
    _create(client, make_payload())
    before = count_reservations()
    r = client.post(
        "/reservations",
        json=make_payload(
            start_time="2026-06-01T18:30:00+00:00",
            end_time="2026-06-01T19:30:00+00:00",
        ),
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"] == "OVERLAP_CONFLICT"
    assert count_reservations() == before == 1


def test_adjacent_reservation_accepted(client):
    seed_table()
    _create(client, make_payload())
    r = client.post(
        "/reservations",
        json=make_payload(
            start_time="2026-06-01T19:00:00+00:00",
            end_time="2026-06-01T20:00:00+00:00",
        ),
    )
    assert r.status_code == 201, r.text
    assert count_reservations() == 2


def test_naive_start_datetime_400(client):
    seed_table()
    r = client.post(
        "/reservations",
        json=make_payload(
            start_time="2026-06-01T18:00:00",
            end_time="2026-06-01T19:00:00+00:00",
        ),
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"] == "NAIVE_DATETIME"
    assert count_reservations() == 0


def test_naive_end_datetime_400(client):
    seed_table()
    r = client.post(
        "/reservations",
        json=make_payload(
            start_time="2026-06-01T18:00:00+00:00",
            end_time="2026-06-01T19:00:00",
        ),
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"] == "NAIVE_DATETIME"
    assert count_reservations() == 0


def test_end_equal_to_start_400(client):
    seed_table()
    r = client.post(
        "/reservations",
        json=make_payload(
            start_time="2026-06-01T18:00:00+00:00",
            end_time="2026-06-01T18:00:00+00:00",
        ),
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"] == "INVALID_TIME_RANGE"
    assert count_reservations() == 0


def test_end_before_start_400(client):
    seed_table()
    r = client.post(
        "/reservations",
        json=make_payload(
            start_time="2026-06-01T19:00:00+00:00",
            end_time="2026-06-01T18:00:00+00:00",
        ),
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"] == "INVALID_TIME_RANGE"
    assert count_reservations() == 0


def test_blank_customer_name_400(client):
    seed_table()
    for blank in ("", "   ", "\t\n"):
        r = client.post("/reservations", json=make_payload(customer_name=blank))
        assert r.status_code == 400, r.text
        assert r.json()["error"] == "INVALID_CUSTOMER_NAME"
    assert count_reservations() == 0


def test_unknown_table_404(client):
    r = client.post("/reservations", json=make_payload(table_id="nope"))
    assert r.status_code == 404, r.text
    assert r.json()["error"] == "UNKNOWN_TABLE"
    assert count_reservations() == 0


def test_missing_reservation_field_422(client):
    seed_table()
    body = make_payload()
    del body["start_time"]
    r = client.post("/reservations", json=body)
    assert r.status_code == 422


OVERLAP_CASES = {
    "partial_tail": ("2026-06-01T18:30:00+00:00", "2026-06-01T19:30:00+00:00"),
    "partial_head": ("2026-06-01T17:30:00+00:00", "2026-06-01T18:30:00+00:00"),
    "contained": ("2026-06-01T18:15:00+00:00", "2026-06-01T18:45:00+00:00"),
    "identical": ("2026-06-01T18:00:00+00:00", "2026-06-01T19:00:00+00:00"),
    "covers": ("2026-06-01T17:00:00+00:00", "2026-06-01T20:00:00+00:00"),
}


@pytest.mark.parametrize("case", sorted(OVERLAP_CASES))
def test_overlap_variants_409(client, case):
    seed_table()
    _create(client, make_payload())
    start, end = OVERLAP_CASES[case]
    payload = make_payload(start_time=start, end_time=end)
    r = client.post("/reservations", json=payload)
    assert r.status_code == 409, r.text
    assert r.json()["error"] == "OVERLAP_CONFLICT"
    assert count_reservations() == 1
    assert count_key(payload["idempotency_key"]) == 0


def test_overlap_on_other_table_allowed(client):
    seed_table("t1")
    seed_table("t2")
    _create(client, make_payload())
    r = client.post("/reservations", json=make_payload(table_id="t2"))
    assert r.status_code == 201, r.text
    assert count_reservations() == 2
