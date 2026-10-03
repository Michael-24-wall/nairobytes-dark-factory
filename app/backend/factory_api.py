from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from .agent_runtime import AgentRuntime
from .db import session
from .factory import MAX_REPAIR_ROUNDS, execute_factory

router = APIRouter(prefix="/api/factory", tags=["factory"])


class RunCreate(BaseModel):
    project_id: UUID
    idempotency_key: str = Field(default="", max_length=160)


class ApprovalBody(BaseModel):
    reason: str = Field(default="", max_length=5000)


def _run_out(row):
    return {key: (str(value) if key in {"id", "project_id"} else value.isoformat() if key.endswith("_at") and value else value) for key, value in dict(row).items()}


@router.get("/metrics")
def get_factory_metrics():
    """Real counts from the database. Nothing here is hardcoded."""
    with session() as conn:
        totals = conn.execute(
            "SELECT (SELECT count(*) FROM factory_runs) AS runs,"
            "       (SELECT count(*) FROM factory_runs WHERE execution_mode='live') AS live_runs,"
            "       (SELECT count(*) FROM factory_tasks) AS tasks,"
            "       (SELECT count(*) FROM factory_artifacts) AS artifacts,"
            "       (SELECT count(*) FROM approvals) AS approvals,"
            "       (SELECT count(*) FROM approvals WHERE status='APPROVED') AS approved"
        ).fetchone()
        run_status = conn.execute(
            "SELECT status, count(*) AS n FROM factory_runs GROUP BY status ORDER BY status"
        ).fetchall()
        roles = conn.execute(
            "SELECT agent_role,"
            "       count(*) AS tasks,"
            "       count(*) FILTER (WHERE status='passed') AS passed,"
            "       count(*) FILTER (WHERE status='failed') AS failed,"
            "       count(*) FILTER (WHERE verdict='PASS') AS verdict_pass,"
            "       count(*) FILTER (WHERE verdict='FAIL') AS verdict_fail"
            "  FROM factory_tasks GROUP BY agent_role ORDER BY agent_role"
        ).fetchall()
        artifacts = conn.execute(
            "SELECT artifact_type, count(*) AS n FROM factory_artifacts GROUP BY artifact_type ORDER BY artifact_type"
        ).fetchall()
        latest = conn.execute(
            "SELECT id, project_id, status, current_stage, execution_mode, error, started_at, completed_at"
            "  FROM factory_runs ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    runtime = AgentRuntime()
    return {
        "totals": dict(totals),
        "runs_by_status": [dict(row) for row in run_status],
        "roles": [dict(row) for row in roles],
        "artifacts_by_type": [dict(row) for row in artifacts],
        "runtime_available": runtime.available(),
        "latest_run": _run_out(latest) if latest else None,
    }


@router.get("/runtime")
def get_factory_runtime():
    """Report whether real agents can run right now, and with which model."""
    runtime = AgentRuntime()
    return {
        "available": runtime.available(),
        **runtime.describe(),
        "max_repair_rounds": MAX_REPAIR_ROUNDS,
        "roles": ["architect", "builder", "breaker", "repair", "verifier"],
    }


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


@router.get("/runs/{run_id}/timeline")
def get_factory_timeline(run_id: UUID):
    """Ordered hand-off chain: every agent task with its predecessor and verdict."""
    with session() as conn:
        run = conn.execute("SELECT * FROM factory_runs WHERE id=%s", (run_id,)).fetchone()
        if run is None:
            raise HTTPException(status_code=404, detail="factory run not found")
        tasks = conn.execute(
            "SELECT id, parent_task_id, sequence, agent_role, task_type, status, verdict,"
            "       handed_to, agent_session_id, input, output, error, started_at, completed_at"
            "  FROM factory_tasks WHERE factory_run_id=%s"
            " ORDER BY sequence, started_at, id",
            (run_id,),
        ).fetchall()
        handoffs = conn.execute(
            "SELECT id, stage, agent_role AS from_role, destination_agent AS to_role, message,"
            "       status, metadata, created_at"
            "  FROM factory_events WHERE factory_run_id=%s AND event_type='handoff'"
            " ORDER BY created_at, id",
            (run_id,),
        ).fetchall()
        events = conn.execute(
            "SELECT id, stage, event_type, message, agent_role AS source_agent, destination_agent,"
            "       status, artifact_path, parent_event_id, metadata, task_id, created_at"
            "  FROM factory_events WHERE factory_run_id=%s ORDER BY created_at, id",
            (run_id,),
        ).fetchall()
        artifacts = conn.execute(
            "SELECT artifact_type, path, sha256 FROM factory_artifacts WHERE factory_run_id=%s ORDER BY created_at",
            (run_id,),
        ).fetchall()
        approval = conn.execute(
            "SELECT status, reason, approved_at FROM approvals WHERE factory_run_id=%s"
            " ORDER BY created_at DESC LIMIT 1",
            (run_id,),
        ).fetchone()
    return {
        "run": _run_out(run),
        "execution_mode": run.get("execution_mode", "deterministic"),
        "runtime": run.get("runtime", {}),
        "tasks": [_run_out(row) for row in tasks],
        "handoffs": [_run_out(row) for row in handoffs],
        "events": [_run_out(row) for row in events],
        "artifacts": [dict(row) for row in artifacts],
        "approval": {key: (value.isoformat() if hasattr(value, "isoformat") else value) for key, value in dict(approval).items()} if approval else None,
    }


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