"""Start a NEW live factory run against the real opencode runtime.

Live mode is forced: if the runtime is unreachable this exits rather than silently
falling back to the deterministic pipeline. Every stage below is a real agent session.
"""

import json
import os
import sys
import time
import uuid

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["FACTORY_EXECUTION_MODE"] = "live"

from app.backend import factory  # noqa: E402
from app.backend.agent_runtime import AgentRuntime  # noqa: E402
from app.backend.db import session  # noqa: E402

PROJECT_NAME = "Nairobytes Tablekeeper Live Verification"


def create_project(conn):
    suffix = uuid.uuid4().hex[:8]
    project = conn.execute(
        "INSERT INTO projects (name, slug, description, project_type, target_users,"
        " business_domain, functional_requirements, nonfunctional_requirements,"
        " technology_preferences) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
        (
            PROJECT_NAME,
            f"nairobytes-tablekeeper-live-{suffix}",
            "A restaurant reservation system that prevents double-booking under concurrency, "
            "supports idempotent retries, and handles timezone-aware reservations.",
            "Reservation System",
            "restaurant operators",
            "restaurant reservations",
            "Customers can create reservations for restaurant tables.\n\n"
            "The system must prevent overlapping reservations for the same table.\n\n"
            "Adjacent reservations are allowed when one reservation ends exactly when another begins.\n\n"
            "Repeated requests with the same idempotency key must not create duplicate reservations.\n\n"
            "The same idempotency key with different request data must be rejected.\n\n"
            "Reservation timestamps must be timezone-aware and normalized consistently.\n\n"
            "The system must remain correct under concurrent booking attempts.",
            "PostgreSQL persistence\nTransactional integrity\nConcurrency safety\n"
            "Idempotent operations\nUTC-normalized timestamps\nAuditability\nAutomated testing",
            "React, Vite, Tailwind CSS",
        ),
    ).fetchone()
    conn.execute("INSERT INTO project_designs (project_id) VALUES (%s)", (project["id"],))

    root = os.path.join(os.environ["TEMP"], "nairobytes-workspaces", str(project["id"]))
    os.makedirs(root, exist_ok=True)
    conn.execute("INSERT INTO project_workspaces (project_id, path) VALUES (%s, %s)",
                 (project["id"], root))
    return project, root


def main():
    runtime = AgentRuntime()
    if not runtime.available():
        print("REFUSING TO RUN: the agent runtime is not reachable at", runtime.base_url)
        return 2

    with session() as conn:
        project, workspace_path = create_project(conn)
        run = conn.execute(
            "INSERT INTO factory_runs (idempotency_key, project_id, execution_mode)"
            " VALUES (%s, %s, 'live') RETURNING id",
            (f"live-verify-{int(time.time())}-{uuid.uuid4().hex[:8]}", project["id"]),
        ).fetchone()

    run_id = run["id"]
    print(f"RUN_ID={run_id}", flush=True)
    print(f"PROJECT_ID={project['id']}", flush=True)
    print(f"WORKSPACE={workspace_path}", flush=True)

    started = time.monotonic()
    factory.execute_factory(project["id"], run_id)
    print(f"\nPIPELINE WALL TIME: {time.monotonic() - started:.1f}s", flush=True)

    with session() as conn:
        final = conn.execute("SELECT status, current_stage, error, execution_mode, runtime,"
                             " started_at, completed_at FROM factory_runs WHERE id=%s",
                             (run_id,)).fetchone()
        tasks = conn.execute("SELECT sequence, agent_role, task_type, status, verdict, handed_to,"
                             " agent_session_id, started_at, completed_at, left(error,300) AS error,"
                             " left(output,300) AS output_head"
                             "  FROM factory_tasks WHERE factory_run_id=%s ORDER BY sequence, started_at",
                             (run_id,)).fetchall()
        handoffs = conn.execute("SELECT stage, agent_role, destination_agent, message, created_at"
                                "  FROM factory_events WHERE factory_run_id=%s AND event_type='handoff'"
                                " ORDER BY created_at, id", (run_id,)).fetchall()
        artifacts = conn.execute("SELECT artifact_type, path, sha256 FROM factory_artifacts"
                                 " WHERE factory_run_id=%s ORDER BY created_at", (run_id,)).fetchall()
        events = conn.execute("SELECT event_type, count(*) AS n FROM factory_events"
                              " WHERE factory_run_id=%s GROUP BY event_type ORDER BY event_type",
                              (run_id,)).fetchall()
        tool_events = conn.execute("SELECT stage, message, created_at FROM factory_events"
                                   " WHERE factory_run_id=%s AND event_type='agent_tool'"
                                   " ORDER BY created_at, id", (run_id,)).fetchall()
        approval = conn.execute("SELECT status, approval_type FROM approvals WHERE factory_run_id=%s",
                                (run_id,)).fetchone()

    dump = lambda rows: json.dumps([{k: str(v) for k, v in dict(r).items()} for r in rows], indent=2)
    print("\n=== FINAL RUN ===")
    print(json.dumps({k: str(v) for k, v in dict(final).items()}, indent=2))
    print("\n=== TASK EVENT COUNTS ===")
    print(dump(events))
    print("\n=== TASKS ===")
    print(dump(tasks))
    print("\n=== HANDOFFS ===")
    print(dump(handoffs))
    print("\n=== ARTIFACTS ===")
    print(json.dumps([dict(r) for r in artifacts], indent=2))
    print("\n=== REAL AGENT TOOL EVENTS ===")
    print(dump(tool_events))
    print("\n=== APPROVAL ===")
    print(json.dumps(dict(approval) if approval else None, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())