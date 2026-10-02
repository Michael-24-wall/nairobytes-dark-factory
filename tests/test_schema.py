import psycopg
import pytest

from app.backend.db import session


def _seed_table(conn, table_id="t1", capacity=4):
    conn.execute(
        "INSERT INTO tables (table_id, capacity) VALUES (%s, %s)",
        (table_id, capacity),
    )


def _insert_reservation(conn, **kw):
    kw.setdefault("customer_name", "Alice")
    kw.setdefault("table_id", "t1")
    kw.setdefault("start_time", "2026-06-01T18:00:00+00:00")
    kw.setdefault("end_time", "2026-06-01T19:00:00+00:00")
    kw.setdefault("idempotency_key", "key-1")
    kw.setdefault("request_hash", "hash-1")
    conn.execute(
        "INSERT INTO reservations"
        " (customer_name, table_id, start_time, end_time, idempotency_key, request_hash)"
        " VALUES (%(customer_name)s, %(table_id)s, %(start_time)s, %(end_time)s,"
        "         %(idempotency_key)s, %(request_hash)s)",
        kw,
    )


def test_db_rejects_overlapping_insert(database):
    with session() as conn:
        _seed_table(conn)
        _insert_reservation(conn)
        with pytest.raises(psycopg.errors.ExclusionViolation):
            _insert_reservation(
                conn,
                start_time="2026-06-01T18:30:00+00:00",
                end_time="2026-06-01T19:30:00+00:00",
                idempotency_key="key-2",
                request_hash="hash-2",
            )


def test_db_allows_back_to_back_insert(database):
    with session() as conn:
        _seed_table(conn)
        _insert_reservation(conn)
        _insert_reservation(
            conn,
            start_time="2026-06-01T19:00:00+00:00",
            end_time="2026-06-01T20:00:00+00:00",
            idempotency_key="key-2",
            request_hash="hash-2",
        )
        count = conn.execute("SELECT count(*) AS count FROM reservations").fetchone()["count"]
    assert count == 2


def test_db_rejects_duplicate_idempotency_key(database):
    with session() as conn:
        _seed_table(conn)
        _insert_reservation(conn)
        with pytest.raises(psycopg.errors.UniqueViolation):
            _insert_reservation(
                conn,
                start_time="2026-06-01T21:00:00+00:00",
                end_time="2026-06-01T22:00:00+00:00",
                idempotency_key="key-1",
                request_hash="hash-2",
            )


def test_db_rejects_end_before_start(database):
    with session() as conn:
        _seed_table(conn)
        with pytest.raises(psycopg.errors.CheckViolation):
            _insert_reservation(
                conn,
                start_time="2026-06-01T19:00:00+00:00",
                end_time="2026-06-01T18:00:00+00:00",
            )


def test_db_rejects_unknown_table_fk(database):
    with session() as conn:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            _insert_reservation(conn, table_id="missing")


def test_db_rejects_zero_capacity(database):
    with session() as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("INSERT INTO tables (table_id, capacity) VALUES ('bad', 0)")
