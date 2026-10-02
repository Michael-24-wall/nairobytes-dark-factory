from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from .db import session
from .factory import execute_factory

router = APIRouter(prefix="/api/factory", tags=["factory"])


class RunCreate(BaseModel):
    project_id: UUID
    idempotency_key: str = Field(default="", max_length=160)


class ApprovalBody(BaseModel):
    reason: str = Field(default="", max_length=5000)


def _run_out(row):
    return {key: (str(value) if key in {"id", "project_id"} else value.isoformat() if key.endswith("_at") and value else value) for key, value in dict(row).items()}


@router.post("/runs", status_code=202)
def start_factory_run(body: RunCreate, background_tasks: BackgroundTasks):
    key = body.idempotency_key.strip() or f"run-{uuid4()}"
    with session() as conn:
        project = conn.execute("SELECT id FROM projects WHERE id=%s", (body.project_id,)).fetchone()
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        existing = conn.execute("SELECT * FROM factory_runs WHERE idempotency_key=%s", (key,)).fetchone()
        if existing:
            return _run_out(existing)
        run = conn.execute("INSERT INTO factory_runs (idempotency_key, project_id) VALUES (%s, %s) RETURNING *", (key, body.project_id)).fetchone()
        run_id = run["id"]
    background_tasks.add_task(execute_factory, body.project_id, run_id)
    return _run_out(run)


@router.get("/runs/{run_id}")
def get_factory_run(run_id: UUID):
    with session() as conn:
        run = conn.execute("SELECT * FROM factory_runs WHERE id=%s", (run_id,)).fetchone()
        if run is None:
            raise HTTPException(status_code=404, detail="factory run not found")
        return _run_out(run)


@router.get("/runs/{run_id}/events")
def get_factory_events(run_id: UUID):
    with session() as conn:
        rows = conn.execute("SELECT * FROM factory_events WHERE factory_run_id=%s ORDER BY created_at, id", (run_id,)).fetchall()
    return [_run_out(row) for row in rows]


@router.get("/runs/{run_id}/tasks")
def get_factory_tasks(run_id: UUID):
    with session() as conn:
        rows = conn.execute("SELECT * FROM factory_tasks WHERE factory_run_id=%s ORDER BY started_at, id", (run_id,)).fetchall()
    return [_run_out(row) for row in rows]


@router.post("/runs/{run_id}/cancel")
def cancel_factory_run(run_id: UUID):
    with session() as conn:
        run = conn.execute("UPDATE factory_runs SET status='cancelled', current_stage='cancelled', completed_at=now(), updated_at=now() WHERE id=%s AND status IN ('queued', 'planning') RETURNING *", (run_id,)).fetchone()
        if run is None:
            raise HTTPException(status_code=409, detail="run is no longer cancellable")
        conn.execute("INSERT INTO factory_events (factory_run_id, stage, event_type, message) VALUES (%s, 'cancelled', 'run_cancelled', 'Human cancelled the factory run.')", (run_id,))
        return _run_out(run)


@router.post("/runs/{run_id}/approve")
def approve_factory_run(run_id: UUID, body: ApprovalBody):
    with session() as conn:
        run = conn.execute("SELECT * FROM factory_runs WHERE id=%s", (run_id,)).fetchone()
        if run is None:
            raise HTTPException(status_code=404, detail="factory run not found")
        if run["status"] != "awaiting_approval":
            raise HTTPException(status_code=409, detail="run is not awaiting approval")
        conn.execute("UPDATE approvals SET status='APPROVED', reason=%s, approved_at=now() WHERE factory_run_id=%s AND approval_type='deployment' AND status='PENDING'", (body.reason, run_id))
        approved = conn.execute("UPDATE factory_runs SET status='approved', current_stage='approved', updated_at=now() WHERE id=%s RETURNING *", (run_id,)).fetchone()
        conn.execute("INSERT INTO factory_events (factory_run_id, stage, event_type, message) VALUES (%s, 'approved', 'human_approved', 'Human approval persisted. Deployment remains not configured.')", (run_id,))
        return _run_out(approved)