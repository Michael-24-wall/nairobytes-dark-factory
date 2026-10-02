import uuid

from app.backend.db import session


def uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def seed_table(table_id: str = "t1", capacity: int = 4) -> None:
    with session() as conn:
        conn.execute(
            "INSERT INTO tables (table_id, capacity) VALUES (%s, %s)"
            " ON CONFLICT (table_id) DO NOTHING",
            (table_id, capacity),
        )


def make_payload(**overrides) -> dict:
    body = {
        "customer_name": "Alice",
        "table_id": "t1",
        "start_time": "2026-06-01T18:00:00+00:00",
        "end_time": "2026-06-01T19:00:00+00:00",
        "idempotency_key": uniq("key"),
    }
    body.update(overrides)
    return body


def count_reservations(where: str = "", params=()) -> int:
    sql = "SELECT count(*) AS count FROM reservations"
    if where:
        sql += f" WHERE {where}"
    with session() as conn:
        return conn.execute(sql, params).fetchone()["count"]


def count_key(key: str) -> int:
    return count_reservations("idempotency_key = %s", (key,))


def overlapping_pair_count() -> int:
    """I1: number of distinct active same-table pairs whose ranges intersect."""
    with session() as conn:
        row = conn.execute(
            "SELECT count(*) AS count"
            "  FROM reservations a"
            "  JOIN reservations b"
            "    ON a.table_id = b.table_id"
            "   AND a.reservation_id < b.reservation_id"
            " WHERE a.status = 'active' AND b.status = 'active'"
            "   AND a.start_time < b.end_time"
            "   AND b.start_time < a.end_time"
        ).fetchone()
    return row["count"]


def fetch_reservation(reservation_id: str) -> dict:
    with session() as conn:
        return conn.execute(
            "SELECT reservation_id, customer_name, table_id, start_time, end_time,"
            "       idempotency_key, status, created_at, request_hash"
            "  FROM reservations WHERE reservation_id = %s",
            (reservation_id,),
        ).fetchone()


def all_reservations() -> list:
    with session() as conn:
        return conn.execute(
            "SELECT reservation_id, status FROM reservations ORDER BY created_at"
        ).fetchall()
