"""Real, single bounded Architect stage against the live opencode runtime.

This proves the fix on the actual failure: the Architect must produce evidence/plan.md
and hand off, inside its budget, without running a feasibility spike.
"""

import json
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["FACTORY_EXECUTION_MODE"] = "live"

from app.backend import factory  # noqa: E402
from app.backend.agent_runtime import AgentRuntime, AgentRuntimeUnavailable, AgentTimeout  # noqa: E402
from app.backend.db import session  # noqa: E402

REQUIREMENTS = (
    "## Project\n\n"
    "- Name: Nairobytes Tablekeeper Live Verification\n"
    "- Type: Reservation System\n"
    "- Description: Prevents double-booking under concurrency, supports idempotent retries.\n\n"
    "## Functional requirements\n\n"
    "Customers can create reservations for restaurant tables.\n\n"
    "The system must prevent overlapping reservations for the same table.\n\n"
    "Adjacent reservations are allowed when one ends exactly when another begins.\n\n"
    "Repeated requests with the same idempotency key must not create duplicates.\n\n"
    "The same idempotency key with different request data must be rejected.\n\n"
    "Reservation timestamps must be timezone-aware and normalized consistently.\n\n"
    "The system must remain correct under concurrent booking attempts.\n\n"
    "## Non-functional requirements\n\n"
    "PostgreSQL persistence, transactional integrity, concurrency safety, idempotent operations, "
    "UTC-normalized timestamps, auditability, automated testing.\n\n"
    "## Technology preferences\n\n"
    "React, Vite, Tailwind CSS\n"
)


def main():
    runtime = AgentRuntime()
    if not runtime.available():
        print("REFUSING: runtime not reachable at", runtime.base_url)
        return 2

    budget = runtime.budget_for("architect")
    print("ARCHITECT BUDGET:", json.dumps(budget.describe(), indent=2))

    workspace = Path(os.environ["TEMP"]) / "nairobytes-live-architect-check" / uuid.uuid4().hex[:8]
    workspace.mkdir(parents=True, exist_ok=True)

    with session() as conn:
        project = conn.execute(
            "INSERT INTO projects (name, slug, description, project_type, functional_requirements,"
            " nonfunctional_requirements, technology_preferences)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            ("Architect bounded check", f"bounded-{uuid.uuid4().hex[:8]}",
             "bounded architect check", "Reservation System",
             "prevent overlapping reservations", "PostgreSQL", "React"),
        ).fetchone()
        run = conn.execute(
            "INSERT INTO factory_runs (idempotency_key, project_id, execution_mode)"
            " VALUES (%s, %s, 'live') RETURNING id",
            (f"bounded-check-{uuid.uuid4().hex[:12]}", project["id"]),
        ).fetchone()

    events = []
    started = time.monotonic()
    try:
        result = runtime.run(
            "architect",
            factory.load_mandate("architect"),
            "\n\n".join([
                factory._handoff_note("architect", "produce the executable plan", 1),
                f"## Workspace\n\n{workspace}",
                REQUIREMENTS + "\n\nProduce ONE artifact: `evidence/plan.md` with these exact sections: "
                "`# Requirements`, `# Invariants`, `# Architecture`, `# Data Model`, `# API Requirements`, "
                "`# Implementation Tasks`, `# Acceptance Tests`, `# Risks`, `# Handoff`.\n"
                "Plan from the requirements above. You have a hard budget of at most 8 tool calls and "
                "4 minutes, enforced by the factory: if you exceed it the session is aborted and the stage "
                "FAILS. Do NOT install packages, do NOT run code, tests, builds, servers or databases, and "
                "do NOT run feasibility spikes or prototypes. The only file you write is `evidence/plan.md`; "
                "write it as your first and only write. Any decision you cannot settle without running "
                "something goes in `# Risks` as an explicit open question for the Builder or Verifier to "
                "prove later.\n"
                "As soon as `evidence/plan.md` contains all sections, write your hand-off summary and stop: "
                "the stage completes as soon as the artifact exists.",
                "",
            ]),
            str(workspace),
            on_progress=lambda kind, detail: (events.append((kind, detail)),
                                              print(f"  [{time.monotonic() - started:6.1f}s] {kind}: {detail}")),
            budget=budget,
        )
    except AgentTimeout as error:
        print("\nARCHITECT TIMED OUT:", json.dumps(error.diagnostics(), indent=2))
        return 1
    except AgentRuntimeUnavailable as error:
        print("RUNTIME UNAVAILABLE:", error)
        return 2

    plan = workspace / "evidence" / "plan.md"
    print(f"\n=== RESULT (wall {time.monotonic() - started:.1f}s) ===")
    print("session_id      :", result["session_id"])
    print("completed_by    :", result["completed_by"])
    print("elapsed_seconds :", result["elapsed_seconds"])
    print("tool_calls      :", result["tool_calls"])
    print("tool_seconds    :", result["tool_seconds"])
    print("last_tool       :", result["last_tool"], "|", result["last_tool_title"])
    print("artifact exists :", plan.is_file())
    if plan.is_file():
        text = plan.read_text(encoding="utf-8")
        print("artifact bytes  :", len(text))
        for section in ("# Requirements", "# Invariants", "# Architecture", "# Data Model",
                        "# API Requirements", "# Implementation Tasks", "# Acceptance Tests",
                        "# Risks", "# Handoff"):
            print(f"  {'OK ' if section in text else 'MISSING'} {section}")
    files = sorted(str(p.relative_to(workspace)) for p in workspace.rglob("*") if p.is_file())
    print("files written   :", files)
    print("\n=== FINAL HANDOFF TEXT ===")
    print(result["text"][:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())