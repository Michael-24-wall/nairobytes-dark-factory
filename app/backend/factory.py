import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from .agent_runtime import AgentRuntime, AgentRuntimeUnavailable, AgentTimeout
from .db import session

FACTORY_ROOT = Path(__file__).resolve().parents[2] / "factory"

MAX_REPAIR_ROUNDS = int(os.getenv("FACTORY_MAX_REPAIR_ROUNDS", "2") or 2)


# ---------------------------------------------------------------------------
# workspace helpers
# ---------------------------------------------------------------------------


def _workspace(conn, project_id):
    row = conn.execute("SELECT path FROM project_workspaces WHERE project_id=%s", (project_id,)).fetchone()
    if row is None:
        raise RuntimeError("project workspace not found")
    path = Path(row["path"]).resolve()
    root = path.parent.parent if path.parent.name == str(project_id) else path.parent
    if path == root or root not in path.parents:
        raise RuntimeError("invalid project workspace")
    path.mkdir(parents=True, exist_ok=True)
    return path


def workspace_for(conn, project_id):
    return _workspace(conn, project_id)


def _command(command, cwd):
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=300)
    return result.returncode, result.stdout, result.stderr


def _project(conn, project_id):
    project = conn.execute("SELECT * FROM projects WHERE id=%s", (project_id,)).fetchone()
    design = conn.execute("SELECT * FROM project_designs WHERE project_id=%s", (project_id,)).fetchone()
    assets = conn.execute("SELECT * FROM project_assets WHERE project_id=%s", (project_id,)).fetchall()
    if project is None or design is None:
        raise RuntimeError("project requirements or design are missing")
    return project, design, assets


# ---------------------------------------------------------------------------
# persistence helpers (short transactions; agents hold no connection)
# ---------------------------------------------------------------------------


def _emit(conn, run_id, stage, event_type, message, agent_role="", task_id=None,
          destination_agent="", status="", artifact_path="", parent_event_id=None, metadata=None):
    """Persist one durable factory event. Everything the UI shows comes from here."""
    conn.execute(
        "INSERT INTO factory_events (factory_run_id, stage, event_type, message, agent_role,"
        " source_agent, destination_agent, status, artifact_path, parent_event_id, metadata, task_id)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            run_id, stage, event_type, (message or "")[:4000], agent_role or "",
            agent_role or "", destination_agent or "", status or "", artifact_path or "",
            parent_event_id, Jsonb(metadata or {}), task_id,
        ),
    )


def _set_stage(conn, run_id, status, message, agent_role=""):
    conn.execute(
        "UPDATE factory_runs SET status=%s, current_stage=%s, updated_at=now(),"
        " started_at=COALESCE(started_at, now()) WHERE id=%s",
        (status, status, run_id),
    )
    _emit(conn, run_id, status, "stage_started", message, agent_role)


def _open_task(conn, run_id, role, task_type, task_input, parent_task_id, sequence):
    row = conn.execute(
        "INSERT INTO factory_tasks (factory_run_id, agent_role, task_type, status, input, parent_task_id, sequence)"
        " VALUES (%s, %s, %s, 'running', %s, %s, %s) RETURNING id",
        (run_id, role, task_type, (task_input or "")[:8000], parent_task_id, sequence),
    ).fetchone()
    return row["id"]


def _close_task(conn, task_id, status, output="", error="", verdict="", session_id="", handed_to=""):
    conn.execute(
        "UPDATE factory_tasks SET status=%s, output=%s, error=%s, verdict=%s,"
        " agent_session_id=%s, handed_to=%s, completed_at=now() WHERE id=%s",
        (status, (output or "")[:20000], (error or "")[:8000], verdict or "", session_id or "", handed_to or "", task_id),
    )


def _handoff(conn, run_id, stage, from_role, to_role, task_id=None, note=""):
    """Record an explicit, human-readable agent-to-agent hand-off.

    This is the REAL RECORD the console renders: "Architect finished and handed
    off to Builder." Every boundary in both pipelines goes through here, and the
    task row keeps a durable ``handed_to`` pointer.
    """
    if task_id is not None:
        conn.execute("UPDATE factory_tasks SET handed_to=%s WHERE id=%s", (to_role, task_id))
    message = f"{from_role.capitalize()} finished and handed off to {to_role.capitalize()}."
    if note:
        message = f"{message} {note}"
    _emit(conn, run_id, stage, "handoff", message, from_role, task_id,
          destination_agent=to_role, status="COMPLETED",
          metadata={"from_agent": from_role, "to_agent": to_role, "note": note})


def _artifact(conn, run_id, workspace, relative_path, artifact_type):
    path = (workspace / relative_path).resolve()
    if workspace not in path.parents or not path.is_file():
        raise RuntimeError(f"artifact missing: {relative_path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    conn.execute(
        "INSERT INTO factory_artifacts (factory_run_id, artifact_type, path, sha256) VALUES (%s, %s, %s, %s)",
        (run_id, artifact_type, str(relative_path), digest),
    )
    return str(relative_path)


def _is_cancelled(run_id):
    with session() as conn:
        row = conn.execute("SELECT status FROM factory_runs WHERE id=%s", (run_id,)).fetchone()
    return bool(row and row["status"] == "cancelled")


# ---------------------------------------------------------------------------
# agent stage execution
# ---------------------------------------------------------------------------


def load_mandate(role):
    """Role mandate plus the shared factory protocol."""
    parts = []
    for candidate in (FACTORY_ROOT / role / "mandate.md", FACTORY_ROOT / "protocol.md"):
        try:
            parts.append(candidate.read_text(encoding="utf-8"))
        except OSError:
            continue
    if not parts:
        parts.append(f"You are the {role} agent in a software factory. Never fabricate evidence.")
    return "\n\n".join(parts)


def _handoff_note(role, task_type, sequence):
    return (
        f"You are the {role} in the Nairobytes Dark Factory. This is stage {sequence} of a live run.\n\n"
        f"Your assignment: {task_type}\n\n"
        "Work inside the assigned workspace only. Follow your mandate and the factory protocol.\n\n"
        "## COMPLETION (bounded task)\n\n"
        "You own ONE bounded deliverable. When that deliverable exists and you have written your "
        "hand-off message, you are DONE: stop immediately. Do not start further exploration, "
        "refactoring, or any work that belongs to another role.\n"
        "End your final message with the required verdict line when your role is a judging role."
    )


def run_agent_stage(runtime, run_id, role, stage, task_type, task_brief, workspace, sequence,
                    parent_task_id=None, handoff_input="", verdict_required=False, artifact_path=None):
    """Execute one real agent stage and persist its hand-off.

    When ``artifact_path`` is given the stage is bounded by that artifact: as soon
    as the file exists and the agent has written its hand-off, the stage completes
    and the agent session is aborted. The agent is never allowed to loop past its
    assigned deliverable.

    The stage also runs under a per-role work budget (see ``agent_runtime.ROLE_BUDGETS``).
    Every budget breach aborts the real session and persists ``agent_failed`` with the
    runtime, role, task, session, elapsed time, last known tool call and the reason.
    A timeout is never converted into a pass.
    """
    mandate = load_mandate(role)
    prompt = "\n\n".join(
        part for part in (
            _handoff_note(role, task_type, sequence),
            f"## Workspace\n\n{workspace}",
            task_brief,
            f"## Handoff from the previous agent\n\n{handoff_input}" if handoff_input else "",
        ) if part
    )

    limits = runtime.budget_for(role)
    completion_check = None
    if artifact_path:
        target = (workspace / artifact_path).resolve()
        def completion_check():  # noqa: E306 - closes over target
            return target.is_file() and target.stat().st_size > 0

    with session() as conn:
        task_id = _open_task(conn, run_id, role, task_type, f"{task_brief}\n\n{handoff_input}", parent_task_id, sequence)
        _emit(conn, run_id, stage, "agent_started", f"{role} started {task_type}.", role, task_id,
              destination_agent="", status="RUNNING",
              metadata={"artifact_required": artifact_path or "", "sequence": sequence,
                        "budget": limits.describe()})

    def on_progress(kind, detail):
        with session() as conn:
            _emit(conn, run_id, stage, f"agent_{kind}", detail, role, task_id)

    try:
        result = runtime.run(
            role,
            mandate,
            prompt,
            str(workspace),
            on_progress=on_progress,
            should_cancel=lambda: _is_cancelled(run_id),
            completion_check=completion_check,
            budget=limits,
        )
    except AgentRuntimeUnavailable as error:
        with session() as conn:
            _close_task(conn, task_id, "failed", error=str(error))
            _emit(conn, run_id, stage, "agent_failed", f"{role} could not complete: {error}", role, task_id,
                  status="FAILED", metadata={"kind": "runtime_unavailable", "reason": str(error)})
        raise
    except AgentTimeout as error:
        diagnostics = error.diagnostics()
        with session() as conn:
            _close_task(conn, task_id, "failed", error=str(error), session_id=diagnostics.get("session_id", ""))
            _emit(conn, run_id, stage, "agent_failed",
                  f"{role} failed: {error} (session {diagnostics.get('session_id') or 'n/a'}, "
                  f"elapsed {diagnostics['elapsed_seconds']}s, last tool {diagnostics.get('last_tool') or 'n/a'}"
                  f"{': ' + diagnostics['last_tool_title'] if diagnostics.get('last_tool_title') else ''})",
                  role, task_id, status="FAILED",
                  metadata={**diagnostics, "runtime": runtime.describe(), "stage": stage,
                            "task_id": str(task_id), "agent_role": role})
        raise

    verdict = result.get("verdict")

    # An agent that produced no text did not complete its stage. A stalled model can end
    # a session with an empty assistant message; handing that off as a finished stage
    # would pass an empty brief to the next agent and record a completion that never
    # happened. Fail closed instead.
    if not (result.get("text") or "").strip():
        with session() as conn:
            _close_task(conn, task_id, "failed",
                        error=f"{role} produced no output; the session ended without a hand-off",
                        session_id=result["session_id"])
            _emit(conn, run_id, stage, "agent_failed",
                  f"{role} produced no output; the session ended without a hand-off "
                  f"(session {result['session_id']}).", role, task_id, status="FAILED",
                  metadata={"kind": "empty_output", "role": role,
                            "session_id": result["session_id"],
                            "task_id": str(task_id), "stage": stage,
                            "elapsed_seconds": result.get("elapsed_seconds"),
                            "tool_calls": result.get("tool_calls"),
                            "tool_errors": (result.get("errors") or [])[:5],
                            "runtime": runtime.describe()})
        result["task_id"] = task_id
        result["failed"] = True
        return result

    if verdict_required and verdict is None:
        with session() as conn:
            _close_task(conn, task_id, "unverified", result["text"][:20000],
                        error="no FACTORY_VERDICT line was emitted; treated as FAIL", session_id=result["session_id"])
            _emit(conn, run_id, stage, "agent_unverified",
                  f"{role} emitted no verdict line; treated as FAIL.", role, task_id)
        result["verdict"] = None
        result["task_id"] = task_id
        return result

    status = {"PASS": "passed", "FAIL": "failed"}.get(verdict or "", "unverified" if not verdict_required else "failed")
    with session() as conn:
        _close_task(conn, task_id, status, result["text"][:20000], session_id=result["session_id"], verdict=verdict or "")
        _emit(conn, run_id, stage, "agent_completed",
              f"{role} finished {task_type} (verdict {verdict or 'n/a'}).", role, task_id,
              status="PASSED" if status == "passed" else status.upper(),
              metadata={"completed_by": result.get("completed_by"),
                        "session_id": result.get("session_id"),
                        "tool_calls": result.get("tool_calls"),
                        "tool_seconds": result.get("tool_seconds"),
                        "elapsed_seconds": result.get("elapsed_seconds"),
                        "last_tool": result.get("last_tool"),
                        "budget": result.get("budget")})
    result["task_id"] = task_id
    return result


def run_test_gate(run_id, stage, task_type, workspace, sequence, parent_task_id=None):
    """Deterministic gate: run the workspace test suite for real."""
    with session() as conn:
        task_id = _open_task(conn, run_id, "tester", task_type, "pytest tests -q", parent_task_id, sequence)
    return_code, stdout, stderr = _command([os.environ.get("PYTHON", sys.executable), "-m", "pytest", "tests", "-q"], workspace)
    passed = return_code == 0
    with session() as conn:
        _close_task(conn, task_id, "passed" if passed else "failed",
                    (stdout or "")[-19000:], (stderr or "")[-8000:])
        _emit(conn, run_id, stage, "gate_completed",
              f"tester ran `pytest tests -q` -> {'passed' if passed else 'FAILED'}.", "tester", task_id)
    return {"task_id": task_id, "passed": passed, "stdout": stdout, "stderr": stderr}


# ---------------------------------------------------------------------------
# live agent pipeline
# ---------------------------------------------------------------------------


def _requirements_block(project, design):
    return (
        f"## Project\n\n"
        f"- Name: {project['name']}\n"
        f"- Type: {project['project_type']}\n"
        f"- Description: {project['description']}\n"
        f"- Target users: {project['target_users']}\n"
        f"- Domain: {project['business_domain']}\n\n"
        f"## Functional requirements\n\n{project['functional_requirements']}\n\n"
        f"## Non-functional requirements\n\n{project['nonfunctional_requirements']}\n\n"
        f"## Technology preferences\n\n{project['technology_preferences']}\n\n"
        f"## Design tokens\n\n```json\n"
        f"{json.dumps({key: design[key] for key in ('primary_color', 'secondary_color', 'accent_color', 'background_color', 'text_color', 'button_color', 'visual_style', 'theme')}, indent=2)}\n```\n"
    )


def _seed_generated_tests(workspace):
    tests_dir = workspace / "tests"
    tests_dir.mkdir(exist_ok=True)
    target = tests_dir / "test_generated_site.py"
    if not target.exists():
        target.write_text(
            "from pathlib import Path\n\nROOT = Path(__file__).parents[1]\n\n"
            "def test_generated_site_has_required_files():\n"
            "    assert (ROOT / 'index.html').is_file()\n"
            "    assert (ROOT / 'styles.css').is_file()\n",
            encoding="utf-8",
        )
    return target


def run_live_pipeline(project_id, run_id, workspace, runtime):
    with session() as conn:
        project, design, _assets = _project(conn, project_id)
        _set_stage(conn, run_id, "planning", "Architect is planning the run against live requirements.", "architect")
    requirements = _requirements_block(project, design)
    sequence = 0

    sequence += 1
    architect = run_agent_stage(
        runtime, run_id, "architect", "planning", "produce the executable plan",
        f"{requirements}\n\nProduce ONE artifact: `evidence/plan.md` with these exact sections: "
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
        workspace, sequence, artifact_path="evidence/plan.md",
    )
    if architect.get("failed"):
        raise RuntimeError(f"architect produced no output (session {architect['session_id']})")
    with session() as conn:
        try:
            _artifact(conn, run_id, workspace, "evidence/plan.md", "architecture")
        except RuntimeError as error:
            _emit(conn, run_id, "planning", "artifact_missing", str(error), "architect")
        _handoff(conn, run_id, "planning", "architect", "builder", architect.get("task_id"))
    architect_handoff = architect["text"]

    sequence += 1
    _seed_generated_tests(workspace)
    with session() as conn:
        _artifact(conn, run_id, workspace, "tests/test_generated_site.py", "generated_source")
        _set_stage(conn, run_id, "building", "Builder is implementing the plan with live agents.", "builder")
    builder = run_agent_stage(
        runtime, run_id, "builder", "building", "implement the plan",
        f"{requirements}\n\nImplement the plan in `evidence/plan.md`. Create the runnable project files, then run the "
        "workspace tests yourself and fix real failures. Do not weaken tests to pass.",
        workspace, sequence, handoff_input=architect_handoff,
    )
    if builder.get("failed"):
        raise RuntimeError(f"builder produced no output (session {builder['session_id']})")
    builder_handoff = builder["text"]
    with session() as conn:
        _handoff(conn, run_id, "building", "builder", "tester", builder.get("task_id"))

    sequence += 1
    with session() as conn:
        _set_stage(conn, run_id, "testing", "Tester is running the workspace suite.", "tester")
    first_gate = run_test_gate(run_id, "testing", "generated_tests", workspace, sequence, parent_task_id=None)
    with session() as conn:
        _handoff(conn, run_id, "testing", "tester", "breaker", first_gate["task_id"])

    repair_round = 0
    breaker = None
    breaker_handoff = ""
    while True:
        sequence += 1
        with session() as conn:
            _set_stage(conn, run_id, "breaking" if repair_round == 0 else "retesting",
                       "Breaker is attacking the implementation with live agents.",
                       "breaker")
        breaker = run_agent_stage(
            runtime, run_id, "breaker", "breaking" if repair_round == 0 else "retesting",
            "adversarially attack the invariants",
            "Attack the invariants and requirements in `evidence/plan.md`. Write reproducible attack tests under "
            "`tests/`, run them, and report what you tried, the exact commands, and the real output. "
            "End with FACTORY_VERDICT: PASS or FACTORY_VERDICT: FAIL.",
            workspace, sequence, handoff_input=builder_handoff, verdict_required=True,
        )
        if breaker.get("failed"):
            raise RuntimeError(f"breaker produced no output (session {breaker['session_id']})")
        breaker_handoff = breaker["text"]
        if breaker.get("verdict") == "PASS":
            with session() as conn:
                _handoff(conn, run_id, "breaking" if repair_round == 0 else "retesting",
                         "breaker", "verifier", breaker.get("task_id"))
            break
        if repair_round >= MAX_REPAIR_ROUNDS:
            with session() as conn:
                _emit(conn, run_id, "breaking", "repair_budget_exhausted",
                      f"Breaker still reports FAIL after {MAX_REPAIR_ROUNDS} repair rounds.", "breaker")
                _handoff(conn, run_id, "breaking", "breaker", "verifier", breaker.get("task_id"),
                         "The breaker still reports FAIL; independent verification proceeds with that recorded.")
            break

        repair_round += 1
        sequence += 1
        with session() as conn:
            _set_stage(conn, run_id, "repairing", f"Repair is fixing the defects the Breaker proved (round {repair_round}).", "repair")
        repair = run_agent_stage(
            runtime, run_id, "repair", "repairing", "fix the reproduced defects",
            "Reproduce each reported failure first, then fix the root cause. Never weaken or delete a test to make a "
            "failure disappear. Re-run the failing command and paste the real output.",
            workspace, sequence, handoff_input=breaker_handoff,
        )
        if repair.get("failed"):
            raise RuntimeError(f"repair produced no output (session {repair['session_id']})")
        sequence += 1
        run_test_gate(run_id, "repairing", "retest", workspace, sequence)
        builder_handoff = f"{builder_handoff}\n\n## Repair round {repair_round}\n\n{repair['text']}"
        with session() as conn:
            _handoff(conn, run_id, "repairing", "repair", "breaker", repair.get("task_id"))

    sequence += 1
    with session() as conn:
        _set_stage(conn, run_id, "verifying", "Verifier is independently checking the result.", "verifier")
    verifier = run_agent_stage(
        runtime, run_id, "verifier", "verifying", "independent verification",
        "Independently decide whether the work meets its requirements. Re-run the test suites and the attack tests "
        "yourself. Write `evidence/verification.md` with each requirement, the command you ran, the real output "
        "summary, and PASS or FAIL. Any requirement without direct evidence is FAIL. "
        "End with FACTORY_VERDICT: PASS or FACTORY_VERDICT: FAIL.",
        workspace, sequence,
        handoff_input=f"## Builder\n{builder_handoff}\n\n## Breaker\n{breaker_handoff}",
        verdict_required=True,
    )
    if verifier.get("failed"):
        raise RuntimeError(f"verifier produced no output (session {verifier['session_id']})")

    if verifier.get("verdict") != "PASS":
        with session() as conn:
            _handoff(conn, run_id, "verifying", "verifier", "human", verifier.get("task_id"),
                     "The verifier did not confirm the run, so the human owns the decision.")
            _set_stage(conn, run_id, "failed", "Verifier did not confirm the run. Human review required.", "verifier")
            conn.execute(
                "UPDATE factory_runs SET error=%s, completed_at=now(), updated_at=now() WHERE id=%s",
                ("Verifier verdict was not PASS; the run was not promoted to approval.", run_id),
            )
        return "failed"

    with session() as conn:
        try:
            _artifact(conn, run_id, workspace, "evidence/verification.md", "verification")
        except RuntimeError as error:
            _emit(conn, run_id, "verifying", "artifact_missing", str(error), "verifier")
        _commit_workspace(conn, run_id, project, workspace)
        _handoff(conn, run_id, "verifying", "verifier", "human", verifier.get("task_id"),
                 "Human approval is required before any deployment.")
        _set_stage(conn, run_id, "awaiting_approval", "Verification passed; human approval is required.", "human")
        conn.execute("INSERT INTO approvals (project_id, factory_run_id, approval_type) VALUES (%s, %s, 'deployment')", (project_id, run_id))
        conn.execute("UPDATE factory_runs SET completed_at=now(), updated_at=now() WHERE id=%s", (run_id,))
    return "awaiting_approval"


def _commit_workspace(conn, run_id, project, workspace):
    _command(["git", "init"], workspace)
    _command(["git", "config", "user.email", "factory@localhost"], workspace)
    _command(["git", "config", "user.name", "Nairobytes Factory"], workspace)
    _command(["git", "add", "."], workspace)
    _command(["git", "commit", "-m", f"Generate {project['name']}"], workspace)
    commit_code, commit_hash, _ = _command(["git", "rev-parse", "HEAD"], workspace)
    branch_code, branch, _ = _command(["git", "branch", "--show-current"], workspace)
    if commit_code != 0 or branch_code != 0:
        raise RuntimeError("unable to verify generated commit")
    conn.execute(
        "INSERT INTO git_commits (project_id, factory_run_id, commit_hash, branch, message) VALUES (%s, %s, %s, %s, %s)",
        (project["id"], run_id, commit_hash.strip(), branch.strip() or "master", f"Generate {project['name']}"),
    )


# ---------------------------------------------------------------------------
# deterministic fallback (no agent runtime available)
# ---------------------------------------------------------------------------


def run_deterministic_pipeline(project_id, run_id, workspace):
    with session() as conn:
        project, design, assets = _project(conn, project_id)
        _set_stage(conn, run_id, "planning", "Architect produced templated artifacts (no agent runtime).", "architect")

        architecture = workspace / "architecture"
        architecture.mkdir(exist_ok=True)
        (architecture / "architecture.md").write_text(
            f"# Architecture\n\nProject: {project['name']}\nType: {project['project_type']}\n\n"
            f"## Requirements\n\n{project['functional_requirements']}\n\n"
            f"## Non-functional requirements\n\n{project['nonfunctional_requirements']}\n",
            encoding="utf-8",
        )
        (architecture / "project_structure.md").write_text(
            "# Project Structure\n\n- index.html\n- styles.css\n- public/assets/\n- tests/test_generated_site.py\n",
            encoding="utf-8",
        )
        (architecture / "testing_strategy.md").write_text(
            "# Testing Strategy\n\nTester runs the generated site checks. Breaker inspects required sections and the "
            "production file boundary. Verifier independently checks requirements and evidence.\n",
            encoding="utf-8",
        )
        for name in ("architecture.md", "project_structure.md", "testing_strategy.md"):
            _artifact(conn, run_id, workspace, f"architecture/{name}", "architecture")
        architect_task = _open_task(conn, run_id, "architect", "architecture", "templated", None, 1)
        _close_task(conn, architect_task, "passed", "Architecture artifacts created.")
        _handoff(conn, run_id, "planning", "architect", "builder", architect_task,
                 "The templated plan is ready for implementation.")

        _set_stage(conn, run_id, "building", "Builder created templated files (no agent runtime).", "builder")
        public_assets = workspace / "public" / "assets"
        public_assets.mkdir(parents=True, exist_ok=True)
        for asset in assets:
            source = Path(asset["storage_path"]).resolve()
            if source.is_file():
                shutil.copy2(source, public_assets / asset["filename"])
        (workspace / "index.html").write_text(
            f"<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{project['name']}</title><link rel=\"stylesheet\" href=\"styles.css\"></head>"
            f"<body><main><p class=\"eyebrow\">{project['project_type']}</p><h1>{project['name']}</h1>"
            f"<p>{project['description']}</p></main></body></html>\n",
            encoding="utf-8",
        )
        (workspace / "styles.css").write_text(
            f":root {{ --color-primary: {design['primary_color']}; --color-text: {design['text_color']}; "
            f"--color-background: {design['background_color']}; }} body {{ margin: 0; color: var(--color-text); "
            f"background: var(--color-background); font-family: system-ui, sans-serif; }} main {{ max-width: 760px; "
            f"margin: 0 auto; padding: 12vh 24px; }}\n",
            encoding="utf-8",
        )
        (workspace / "README.md").write_text(f"# {project['name']}\n\nGenerated workspace.\n", encoding="utf-8")
        for name in ("index.html", "styles.css", "README.md"):
            _artifact(conn, run_id, workspace, name, "generated_source")
        builder_task = _open_task(conn, run_id, "builder", "generate_project", "templated", None, 2)
        _close_task(conn, builder_task, "passed", "Runnable static website files created.")
        _handoff(conn, run_id, "building", "builder", "tester", builder_task,
                 "Generated site files are ready for the test gate.")

    _seed_generated_tests(workspace)
    with session() as conn:
        _artifact(conn, run_id, workspace, "tests/test_generated_site.py", "generated_source")
        _set_stage(conn, run_id, "testing", "Tester is executing generated-project checks.", "tester")
    gate = run_test_gate(run_id, "testing", "generated_tests", workspace, 3)
    if not gate["passed"]:
        raise RuntimeError("generated project tests failed")
    with session() as conn:
        _handoff(conn, run_id, "testing", "tester", "breaker", gate["task_id"],
                 "The generated suite passed; the breaker now attacks it.")

    with session() as conn:
        _set_stage(conn, run_id, "breaking", "Breaker inspected generated files (no agent runtime).", "breaker")
        evidence = workspace / "evidence"
        evidence.mkdir(exist_ok=True)
        required = [workspace / "index.html", workspace / "styles.css", workspace / "README.md"]
        missing = [str(path.relative_to(workspace)) for path in required if not path.is_file()]
        (evidence / "breaker_report.md").write_text(
            f"# Breaker Report\n\nResult: {'PASS' if not missing else 'FAIL'}\n\n"
            f"Missing required files: {missing or 'none'}\n",
            encoding="utf-8",
        )
        _artifact(conn, run_id, workspace, "evidence/breaker_report.md", "breaker_report")
        task_id = _open_task(conn, run_id, "breaker", "generated_project_attack", "file presence", None, 4)
        _close_task(conn, task_id, "passed" if not missing else "failed", "Required generated files inspected.",
                    verdict="PASS" if not missing else "FAIL")
        if missing:
            raise RuntimeError("breaker found missing generated files")
        _handoff(conn, run_id, "breaking", "breaker", "tester", task_id,
                 "Breaker PASS; handing back to the tester for the retest gate.")

        _set_stage(conn, run_id, "retesting", "Tester re-confirmed the generated project.", "tester")
    gate = run_test_gate(run_id, "retesting", "retest", workspace, 5)
    if not gate["passed"]:
        raise RuntimeError("generated project retest failed")
    with session() as conn:
        _handoff(conn, run_id, "retesting", "tester", "verifier", gate["task_id"],
                 "The retest gate passed; independent verification begins.")

    with session() as conn:
        _set_stage(conn, run_id, "verifying", "Verifier recorded templated verification (no agent runtime).", "verifier")
        evidence = workspace / "evidence"
        (evidence / "verification.md").write_text(
            "# Verification Report\n\nResult: PASS\n\nTemplated verification: required files exist and tests pass.\n",
            encoding="utf-8",
        )
        _artifact(conn, run_id, workspace, "evidence/verification.md", "verification")
        task_id = _open_task(conn, run_id, "verifier", "independent_verification", "templated", None, 6)
        _close_task(conn, task_id, "passed", "Templated verification recorded.", verdict="PASS")
        _handoff(conn, run_id, "verifying", "verifier", "human", task_id,
                 "Independent verification passed; human approval is required.")
        project, _design, _assets = _project(conn, project_id)
        _commit_workspace(conn, run_id, project, workspace)
        _set_stage(conn, run_id, "awaiting_approval", "Verification passed; human approval is required.", "human")
        conn.execute("INSERT INTO approvals (project_id, factory_run_id, approval_type) VALUES (%s, %s, 'deployment')", (project_id, run_id))
        conn.execute("UPDATE factory_runs SET completed_at=now(), updated_at=now() WHERE id=%s", (run_id,))
    return "awaiting_approval"


# ---------------------------------------------------------------------------
# entrypoint
# ---------------------------------------------------------------------------


def resolve_execution_mode(runtime):
    forced = (os.getenv("FACTORY_EXECUTION_MODE") or "").strip().lower()
    if forced in {"live", "agents"}:
        return "live"
    if forced in {"deterministic", "scripted", "template"}:
        return "deterministic"
    return "live" if runtime.available() else "deterministic"


def execute_factory(project_id: UUID, run_id: UUID):
    runtime = AgentRuntime()
    mode = resolve_execution_mode(runtime)
    try:
        with session() as conn:
            conn.execute("UPDATE factory_runs SET execution_mode=%s, runtime=%s WHERE id=%s",
                         (mode, json.dumps(runtime.describe()), run_id))
            _emit(conn, run_id, "queued", "run_started",
                  f"Factory run started in {mode} mode.", "", status="RUNNING",
                  metadata={"execution_mode": mode})
            if mode == "deterministic":
                _emit(conn, run_id, "queued", "execution_mode_selected",
                      "No reachable agent runtime; running the deterministic template pipeline. Results are templated, "
                      "not agent-produced.", "")
        with session() as conn:
            workspace = _workspace(conn, project_id)
        if mode == "live":
            run_live_pipeline(project_id, run_id, workspace, runtime)
        else:
            run_deterministic_pipeline(project_id, run_id, workspace)
    except Exception as error:  # noqa: BLE001 - the run must always reach a terminal state
        with session() as conn:
            conn.execute(
                "UPDATE factory_runs SET status='failed', current_stage='failed', error=%s, completed_at=now(),"
                " updated_at=now() WHERE id=%s AND status <> 'cancelled'",
                (str(error)[:4000], run_id),
            )
            _emit(conn, run_id, "failed", "run_failed", str(error)[:4000], "")