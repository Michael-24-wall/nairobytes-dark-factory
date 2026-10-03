"""Availability probing: GET /tables/{table_id}/availability."""

from api_helpers import make_payload, seed_table, uniq


def _probe(client, table_id, start, end):
    return client.get(
        f"/tables/{table_id}/availability",
        params={"start_time": start, "end_time": end},
    )


def test_unknown_table_is_reported_without_error(client):
    r = _probe(client, uniq("ghost"), "2026-06-01T18:00:00+00:00", "2026-06-01T19:00:00+00:00")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["table_exists"] is False
    assert data["available"] is False
    assert data["conflicting_reservation_id"] is None


def test_free_window_on_known_table_is_available(client):
    seed_table()
    r = _probe(client, "t1", "2026-06-01T18:00:00+00:00", "2026-06-01T19:00:00+00:00")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["table_exists"] is True
    assert data["available"] is True
    assert data["conflicting_reservation_id"] is None
    assert data["start_time"] == "2026-06-01T18:00:00+00:00"
    assert data["end_time"] == "2026-06-01T19:00:00+00:00"


def test_booked_window_is_unavailable_and_names_the_conflict(client):
    seed_table()
    created = client.post("/reservations", json=make_payload())
    assert created.status_code == 201, created.text
    data = _probe(client, "t1", "2026-06-01T18:00:00+00:00", "2026-06-01T19:00:00+00:00").json()
    assert data["available"] is False
    assert data["conflicting_reservation_id"] == created.json()["reservation_id"]


def test_adjacent_window_stays_available(client):
    seed_table()
    assert client.post("/reservations", json=make_payload()).status_code == 201
    data = _probe(client, "t1", "2026-06-01T19:00:00+00:00", "2026-06-01T20:00:00+00:00").json()
    assert data["available"] is True


def test_partial_overlap_is_unavailable(client):
    seed_table()
    assert client.post("/reservations", json=make_payload()).status_code == 201
    data = _probe(client, "t1", "2026-06-01T18:30:00+00:00", "2026-06-01T19:30:00+00:00").json()
    assert data["available"] is False


def test_enclosing_window_is_unavailable(client):
    seed_table()
    assert client.post("/reservations", json=make_payload()).status_code == 201
    data = _probe(client, "t1", "2026-06-01T17:00:00+00:00", "2026-06-01T20:00:00+00:00").json()
    assert data["available"] is False


def test_offset_equivalence_matches_utc_booking(client):
    seed_table()
    assert client.post("/reservations", json=make_payload()).status_code == 201
    data = _probe(client, "t1", "2026-06-01T21:00:00+03:00", "2026-06-01T22:00:00+03:00").json()
    assert data["available"] is False


def test_other_table_same_window_is_available(client):
    seed_table("t1")
    seed_table("t2")
    assert client.post("/reservations", json=make_payload()).status_code == 201
    data = _probe(client, "t2", "2026-06-01T18:00:00+00:00", "2026-06-01T19:00:00+00:00").json()
    assert data["available"] is True


def test_available_probe_predicts_accepted_booking(client):
    seed_table()
    probe = _probe(client, "t1", "2026-06-01T18:00:00+00:00", "2026-06-01T19:00:00+00:00").json()
    assert probe["available"] is True
    assert client.post("/reservations", json=make_payload()).status_code == 201
    assert _probe(client, "t1", "2026-06-01T18:00:00+00:00", "2026-06-01T19:00:00+00:00").json()["available"] is False


def test_unavailable_probe_predicts_conflict(client):
    seed_table()
    assert client.post("/reservations", json=make_payload()).status_code == 201
    probe = _probe(client, "t1", "2026-06-01T18:00:00+00:00", "2026-06-01T19:00:00+00:00").json()
    assert probe["available"] is False
    r = client.post("/reservations", json=make_payload())
    assert r.status_code == 409, r.text
    assert r.json()["error"] == "OVERLAP_CONFLICT"


def test_naive_timestamps_rejected(client):
    seed_table()
    r = _probe(client, "t1", "2026-06-01T18:00:00", "2026-06-01T19:00:00")
    assert r.status_code == 400, r.text
    assert r.json()["error"] == "NAIVE_DATETIME"


def test_inverted_range_rejected(client):
    seed_table()
    r = _probe(client, "t1", "2026-06-01T19:00:00+00:00", "2026-06-01T18:00:00+00:00")
    assert r.status_code == 400, r.text
    assert r.json()["error"] == "INVALID_TIME_RANGE"


def test_probe_creates_no_rows(client):
    from api_helpers import count_reservations

    seed_table()
    assert client.post("/reservations", json=make_payload()).status_code == 201
    before = count_reservations()
    _probe(client, "t1", "2026-06-01T18:00:00+00:00", "2026-06-01T19:00:00+00:00")
    _probe(client, uniq("ghost"), "2026-06-01T18:00:00+00:00", "2026-06-01T19:00:00+00:00")
    assert count_reservations() == before