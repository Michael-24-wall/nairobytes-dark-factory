import hashlib
import json
import time
from datetime import datetime, timezone

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from psycopg import errors
from pydantic import BaseModel, Field

from .db import session
from .projects import router as projects_router
from .factory_api import router as factory_router
from .github_api import router as github_router
from .payments import router as payments_router

app = FastAPI(title="Nairobytes Dark Factory API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)
app.include_router(projects_router)
app.include_router(factory_router)
app.include_router(github_router)
app.include_router(payments_router)


class TableBody(BaseModel):
    table_id: str = Field(min_length=1)
    capacity: int


class ReservationBody(BaseModel):
    customer_name: str
    table_id: str = Field(min_length=1)
    start_time: datetime
    end_time: datetime
    idempotency_key: str = Field(min_length=1)


def _err(status: int, code: str, message: str = "") -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message})


def _normalize(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc)


def _request_hash(body: ReservationBody) -> str:
    payload = {
        "customer_name": body.customer_name.strip(),
        "table_id": body.table_id,
        "start_time": _normalize(body.start_time).isoformat(),
        "end_time": _normalize(body.end_time).isoformat(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _row_out(row: dict) -> dict:
    out = dict(row)
    out.pop("request_hash", None)
    out["reservation_id"] = str(out["reservation_id"])
    out["start_time"] = _normalize(out["start_time"]).isoformat()
    out["end_time"] = _normalize(out["end_time"]).isoformat()
    out["created_at"] = _normalize(out["created_at"]).isoformat()
    return out


@app.post("/tables", status_code=201)
def create_table(body: TableBody, request: Request):
    if body.capacity < 1:
        return _err(400, "INVALID_CAPACITY", "capacity must be >= 1")
    with session() as conn:
        try:
            conn.execute(
                "INSERT INTO tables (table_id, capacity) VALUES (%s, %s)",
                (body.table_id, body.capacity),
            )
        except errors.UniqueViolation:
            return _err(409, "TABLE_EXISTS", f"table {body.table_id} already exists")
    return {"table_id": body.table_id, "capacity": body.capacity}


AVAILABILITY_SQL = """
SELECT reservation_id
  FROM reservations
 WHERE table_id = %s
   AND status = 'active'
   AND tstzrange(start_time, end_time, '[)') && tstzrange(%s, %s, '[)')
 LIMIT 1
"""


@app.get("/tables/{table_id}/availability")
def check_availability(table_id: str, start_time: datetime, end_time: datetime):
    if start_time.tzinfo is None or end_time.tzinfo is None:
        return _err(400, "NAIVE_DATETIME", "timestamps must include a UTC offset")
    if end_time <= start_time:
        return _err(400, "INVALID_TIME_RANGE", "end_time must be after start_time")

    with session() as conn:
        known = conn.execute(
            "SELECT 1 FROM tables WHERE table_id = %s", (table_id,)
        ).fetchone()
        conflict = None
        if known is not None:
            conflict = conn.execute(
                AVAILABILITY_SQL,
                (table_id, _normalize(start_time), _normalize(end_time)),
            ).fetchone()

    table_exists = known is not None
    return {
        "table_id": table_id,
        "table_exists": table_exists,
        "start_time": _normalize(start_time).isoformat(),
        "end_time": _normalize(end_time).isoformat(),
        "available": table_exists and conflict is None,
        "conflicting_reservation_id": (
            str(conflict["reservation_id"]) if conflict is not None else None
        ),
    }


INSERT_SQL = """
WITH reservation_lock AS MATERIALIZED (
    SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))
)
INSERT INTO reservations
  (customer_name, table_id, start_time, end_time, idempotency_key, request_hash)
SELECT %s, %s, %s, %s, %s, %s
FROM reservation_lock
ON CONFLICT (idempotency_key) DO NOTHING
RETURNING reservation_id, customer_name, table_id, start_time, end_time,
           idempotency_key, status, created_at
"""


@app.post("/reservations", status_code=201)
def create_reservation(body: ReservationBody, request: Request):
    if body.start_time.tzinfo is None or body.end_time.tzinfo is None:
        return _err(400, "NAIVE_DATETIME", "timestamps must include a UTC offset")
    if body.end_time <= body.start_time:
        return _err(400, "INVALID_TIME_RANGE", "end_time must be after start_time")
    if not body.customer_name.strip():
        return _err(400, "INVALID_CUSTOMER_NAME", "customer_name must not be blank")

    rhash = _request_hash(body)
    with session() as conn:
        insert_args = (
            body.table_id,
            body.customer_name.strip(),
            body.table_id,
            _normalize(body.start_time),
            _normalize(body.end_time),
            body.idempotency_key,
            rhash,
        )
        for attempt in range(8):
            try:
                row = conn.execute(INSERT_SQL, insert_args).fetchone()
                break
            except errors.DeadlockDetected:
                if attempt == 7:
                    raise
                time.sleep(0.01 * (2**attempt))
            except errors.ExclusionViolation:
                return _err(409, "OVERLAP_CONFLICT", "table is already booked for this window")
            except errors.ForeignKeyViolation:
                return _err(404, "UNKNOWN_TABLE", f"table {body.table_id} does not exist")

        if row is not None:
            return _row_out(row)

        stored = conn.execute(
            "SELECT reservation_id, customer_name, table_id, start_time, end_time,"
            "       idempotency_key, status, created_at, request_hash"
            "  FROM reservations WHERE idempotency_key = %s",
            (body.idempotency_key,),
        ).fetchone()
        if stored is None:
            return _err(409, "IDEMPOTENCY_CONFLICT", "conflicting concurrent request")
        if stored["request_hash"] != rhash:
            return _err(
                409,
                "IDEMPOTENCY_PAYLOAD_MISMATCH",
                "same idempotency_key with a different payload",
            )
        stored.pop("request_hash", None)
        return JSONResponse(status_code=200, content=_row_out(stored))


@app.get("/reservations/{reservation_id}")
def get_reservation(reservation_id: str):
    try:
        with session() as conn:
            row = conn.execute(
                "SELECT reservation_id, customer_name, table_id, start_time, end_time,"
                "       idempotency_key, status, created_at"
                "  FROM reservations WHERE reservation_id = %s",
                (reservation_id,),
            ).fetchone()
    except errors.InvalidTextRepresentation:
        row = None
    if row is None:
        return _err(404, "NOT_FOUND", "reservation not found")
    return _row_out(row)
