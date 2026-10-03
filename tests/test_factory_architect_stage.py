"""Focused tests for the live Architect stage: bounded plan, artifact and hand-off.

These exercise the real ``run_agent_stage`` persistence path against a scripted agent
runtime. No LLM and no network call happens: the runtime is replaced by a stub that
returns controlled results, so these tests assert what the factory persists.

They cover the regression from the failed live run
db69954a-4cc8-4aa0-85ae-812a7997ab7d, where the Architect never produced a plan.
"""

import pytest

from app.backend import factory
from app.backend.agent_runtime import AgentTimeout
from app.backend.db import session


@pytest.fixture(autouse=True)
def deterministic_mode(monkeypatch):
    """These tests drive one agent stage directly; they never start a full run."""
    monkeypatch.setenv("FACTORY_EXECUTION_MODE", "deterministic")
    yield


class StubRuntime:
    """Stands in for AgentRuntime so no agent and no network is involved."""

    def __init__(self, result=None, error=None, budget=None):
        self.result = result
        self.error = error
        self._budget = budget
        self.calls = []

    def budget_for(self, role):
        from app.backend.agent_runtime import AgentBudget

        return self._budget or AgentBudget(timeout=900)

    def describe(self):
        return {"base_url": "stub", "provider_id": "stub", "model_id": "stub"}

    def run(self, role, mandate, prompt, directory, on_progress=None, should_cancel=None,
            completion_check=None, budget=None):
        self.calls.append({"role": role, "mandate": mandate, "prompt": prompt,
                           "directory": directory, "budget": budget})
        if on_progress:
            on_progress("session", f"{role} session ses_stub opened on stub")
            on_progress("tool", f"{role}: write (evidence/plan.md) completed")
        if self.error is not None:
            raise self.error
        return dict(self.result)


def seed_run_and_workspace(client, key="architect-stage-run"):
    """Create a project and a queued run WITHOUT starting a pipeline.

    Going through ``POST /api/factory/runs`` would run the deterministic pipeline as a
    background task, which creates its own architect task and makes these assertions
    ambiguous. These tests drive one live agent stage directly, so the run row is
    inserted directly and no other stage ever runs.
    """
    project = client.post("/projects", json={
        "name": "Nairobytes Tablekeeper Demo",
        "description": "Reservation system.",
        "project_type": "Reservation System",
        "functional_requirements": "Customers create reservations. No overlapping bookings.",
        "nonfunctional_requirements": "PostgreSQL persistence, concurrency safety.",
        "technology_preferences": "React, Vite, Tailwind CSS",
    }).json()
    with session() as conn:
        run_id = conn.execute(
            "INSERT INTO factory_runs (idempotency_key, project_id, execution_mode, status)"
            " VALUES (%s, %s, 'live', 'planning') RETURNING id",
            (key, project["id"]),
        ).fetchone()["id"]
        workspace = factory.workspace_for(conn, project["id"])
    return project, run_id, workspace


def architect_task(run_id):
    """The single architect task this stage created."""
    with session() as conn:
        return conn.execute(
            "SELECT id, status, error, verdict, agent_session_id, handed_to, agent_role"
            "  FROM factory_tasks WHERE factory_run_id=%s AND agent_role='architect'",
            (run_id,),
        ).fetchone()


class _StopStage(Exception):
    """Stops the pipeline right after the Architect brief is built."""


def stage(client, stub, workspace, run_id, artifact="evidence/plan.md"):
    return factory.run_agent_stage(
        stub, run_id, "architect", "planning", "produce the executable plan",
        "Produce ONE artifact: `evidence/plan.md`.", workspace, sequence=1,
        artifact_path=artifact,
    )


# ---------------------------------------------------------------------------
# the architect mandate itself
# ---------------------------------------------------------------------------


def test_architect_mandate_forbids_execution_and_states_a_bounded_completion():
    """The failed Architect ran a feasibility spike because it was never told not to."""
    mandate = factory.load_mandate("architect")
    assert "evidence/plan.md" in mandate
    assert "do not execute" in mandate.lower() or "You do not execute anything" in mandate
    assert "feasibility spike" in mandate.lower()
    assert "npm" in mandate.lower() or "install packages" in mandate.lower()
    assert "Completion condition" in mandate
    assert "STOP" in mandate


def test_architect_mandate_declares_every_required_plan_section():
    mandate = factory.load_mandate("architect")
    for section in ("# Requirements", "# Invariants", "# Architecture", "# Data Model",
                    "# API Requirements", "# Implementation Tasks", "# Acceptance Tests",
                    "# Risks", "# Handoff"):
        assert section in mandate, section


def test_protocol_tells_planning_roles_not_to_execute_to_justify_themselves():
    protocol = factory.load_mandate("architect")
    assert "role-scoped" in protocol
    assert "stage failure" in protocol


# ---------------------------------------------------------------------------
# architect stage completion + hand-off
# ---------------------------------------------------------------------------


def test_architect_stage_completes_persists_plan_and_hands_off_to_builder(client):
    project, run_id, workspace = seed_run_and_workspace(client)
    plan = workspace / "evidence" / "plan.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text("# Requirements\n1. no overlaps\n\n# Handoff\nstart here\n", encoding="utf-8")

    stub = StubRuntime(result={
        "text": "Plan written. Handing off to Builder.", "verdict": None, "text_len": 0,
        "session_id": "ses_stub", "tool_calls": 3, "errors": [], "completed": True,
        "completed_by": "artifact", "elapsed_seconds": 41.2, "last_tool": "write",
        "last_tool_title": "evidence/plan.md", "tool_seconds": 6.0, "budget": {},
    })
    result = stage(client, stub, workspace, run_id)

    assert result["task_id"]
    # The stage is bounded by the artifact: the runtime was given the completion check.
    assert stub.calls[0]["budget"] is not None

    with session() as conn:
        task = conn.execute("SELECT status, agent_role, agent_session_id, handed_to FROM factory_tasks WHERE id=%s",
                            (result["task_id"],)).fetchone()
        events = conn.execute("SELECT event_type, message, metadata FROM factory_events"
                              " WHERE factory_run_id=%s ORDER BY created_at, id", (run_id,)).fetchall()

    assert task["status"] == "unverified"
    assert task["agent_session_id"] == "ses_stub"

    types = [event["event_type"] for event in events]
    assert "agent_started" in types
    assert "agent_session" in types
    assert "agent_tool" in types
    assert "agent_completed" in types
    # A real tool name is persisted, not an opaque call id.
    tool_events = [event for event in events if event["event_type"] == "agent_tool"]
    assert any("write" in event["message"] for event in tool_events)
    assert all("call_" not in event["message"] for event in tool_events)

    completion = [event for event in events if event["event_type"] == "agent_completed"][0]
    assert completion["metadata"]["completed_by"] == "artifact"
    assert completion["metadata"]["last_tool"] == "write"
    assert completion["metadata"]["tool_seconds"] == 6.0


def test_architect_stage_records_artifact_and_handoff_to_builder(client):
    project, run_id, workspace = seed_run_and_workspace(client, key="architect-handoff-run")
    plan = workspace / "evidence" / "plan.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text("# Requirements\n1. no overlaps\n\n# Handoff\nstart here\n", encoding="utf-8")

    stub = StubRuntime(result={
        "text": "Plan written.", "verdict": None, "session_id": "ses_stub",
        "tool_calls": 2, "errors": [], "completed": True, "completed_by": "artifact",
        "elapsed_seconds": 30.0, "last_tool": "write", "tool_seconds": 5.0, "budget": {},
    })
    result = stage(client, stub, workspace, run_id)

    with session() as conn:
        factory._artifact(conn, run_id, workspace, "evidence/plan.md", "architecture")
        factory._handoff(conn, run_id, "planning", "architect", "builder", result["task_id"])

        artifact = conn.execute("SELECT path, sha256 FROM factory_artifacts WHERE factory_run_id=%s",
                                (run_id,)).fetchone()
        handoff = conn.execute("SELECT message, source_agent, destination_agent, status FROM factory_events"
                               " WHERE factory_run_id=%s AND event_type='handoff'", (run_id,)).fetchone()
        task = conn.execute("SELECT handed_to FROM factory_tasks WHERE id=%s", (result["task_id"],)).fetchone()

    assert artifact["path"] == "evidence/plan.md"
    assert artifact["sha256"]
    assert handoff["source_agent"] == "architect"
    assert handoff["destination_agent"] == "builder"
    assert handoff["status"] == "COMPLETED"
    assert "handed off to Builder" in handoff["message"]
    assert task["handed_to"] == "builder"


def test_architect_stage_prompt_forbids_execution_and_states_the_budget(client):
    """The live pipeline's own Architect brief must forbid executing to get the plan."""
    project, run_id, workspace = seed_run_and_workspace(client, key="architect-prompt-run")
    captured = {}

    def capture(runtime, run_id, role, stage, task_type, task_brief, workspace, sequence, **kwargs):
        captured["brief"] = task_brief
        captured["artifact_path"] = kwargs.get("artifact_path")
        raise _StopStage()

    original = factory.run_agent_stage
    factory.run_agent_stage = capture
    try:
        with pytest.raises(_StopStage):
            factory.run_live_pipeline(project["id"], run_id, workspace, StubRuntime(result={}))
    finally:
        factory.run_agent_stage = original

    brief = captured["brief"]
    assert captured["artifact_path"] == "evidence/plan.md"
    assert "evidence/plan.md" in brief
    assert "Do NOT install packages" in brief
    assert "do NOT run code, tests, builds, servers or databases" in brief
    assert "feasibility spikes" in brief
    assert "8 tool calls" in brief
    assert "The only file you write is `evidence/plan.md`" in brief
    assert "`# Risks` as an explicit open question" in brief
    assert "FAILS" in brief


# ---------------------------------------------------------------------------
# timeout diagnostics: preserved, never a pass
# ---------------------------------------------------------------------------


def test_architect_timeout_records_full_diagnostics_and_is_never_a_pass(client):
    project, run_id, workspace = seed_run_and_workspace(client, key="architect-timeout-run")
    error = AgentTimeout(
        "architect started 12 tool calls, over its budget of 8",
        role="architect", session_id="ses_timeout", elapsed=612.4,
        last_tool="bash", last_tool_title="npm install --no-audit", tool_calls=12,
        kind="tool_call_budget", budget={"timeout_seconds": 900.0, "max_tool_calls": 8},
    )
    stub = StubRuntime(error=error)

    with pytest.raises(AgentTimeout):
        factory.run_agent_stage(stub, run_id, "architect", "planning", "produce the plan",
                                "Produce the plan.", workspace, sequence=1,
                                artifact_path="evidence/plan.md")

    with session() as conn:
        task = conn.execute("SELECT status, error, agent_session_id FROM factory_tasks"
                            " WHERE factory_run_id=%s AND agent_role='architect'", (run_id,)).fetchone()
        failed = conn.execute("SELECT message, status, metadata FROM factory_events"
                              " WHERE factory_run_id=%s AND event_type='agent_failed'", (run_id,)).fetchone()
        completed = conn.execute("SELECT count(*) AS n FROM factory_events"
                                 " WHERE factory_run_id=%s AND event_type='agent_completed'",
                                 (run_id,)).fetchone()

    # Fails closed: task failed, real session recorded, no synthetic completion.
    assert task["status"] == "failed"
    assert task["agent_session_id"] == "ses_timeout"
    assert completed["n"] == 0
    assert failed["status"] == "FAILED"

    metadata = failed["metadata"]
    for key in ("role", "session_id", "elapsed_seconds", "last_tool", "last_tool_title",
                "tool_calls", "kind", "budget", "reason", "runtime", "stage", "task_id",
                "agent_role"):
        assert key in metadata, key
    assert metadata["kind"] == "tool_call_budget"
    assert metadata["last_tool"] == "bash"
    assert metadata["last_tool_title"] == "npm install --no-audit"
    assert metadata["elapsed_seconds"] == 612.4
    assert metadata["runtime"]["model_id"] == "stub"
    assert metadata["agent_role"] == "architect"
    # Human-readable event names the real tool, not an opaque call id.
    assert "bash" in failed["message"]
    assert "npm install" in failed["message"]
    assert "call_" not in failed["message"]


def test_wall_clock_timeout_is_reported_as_a_timeout_not_a_pass(client):
    project, run_id, workspace = seed_run_and_workspace(client, key="architect-wallclock-run")
    error = AgentTimeout("architect exceeded 900s without finishing", role="architect",
                         session_id="ses_wall", elapsed=900.2, last_tool="bash",
                         last_tool_title="node spike2.mjs", tool_calls=30, kind="timeout",
                         budget={"timeout_seconds": 900.0})
    with pytest.raises(AgentTimeout):
        factory.run_agent_stage(StubRuntime(error=error), run_id, "architect", "planning",
                                "produce the plan", "Produce the plan.", workspace, sequence=1,
                                artifact_path="evidence/plan.md")

    with session() as conn:
        failed = conn.execute("SELECT status, metadata FROM factory_events"
                              " WHERE factory_run_id=%s AND event_type='agent_failed'", (run_id,)).fetchone()

    assert failed["status"] == "FAILED"
    assert failed["metadata"]["kind"] == "timeout"
    assert architect_task(run_id)["status"] == "failed"


def test_runtime_unavailable_is_reported_separately_from_a_timeout(client):
    from app.backend.agent_runtime import AgentRuntimeUnavailable

    project, run_id, workspace = seed_run_and_workspace(client, key="architect-unavailable-run")
    error = AgentRuntimeUnavailable("opencode agent runtime is not reachable at http://127.0.0.1:4097")
    with pytest.raises(AgentRuntimeUnavailable):
        factory.run_agent_stage(StubRuntime(error=error), run_id, "architect", "planning",
                                "produce the plan", "Produce the plan.", workspace, sequence=1,
                                artifact_path="evidence/plan.md")

    with session() as conn:
        failed = conn.execute("SELECT status, metadata FROM factory_events"
                              " WHERE factory_run_id=%s AND event_type='agent_failed'", (run_id,)).fetchone()
    assert failed["metadata"]["kind"] == "runtime_unavailable"
    assert failed["status"] == "FAILED"
    assert architect_task(run_id)["status"] == "failed"


# ---------------------------------------------------------------------------
# judging roles still require a verdict
# ---------------------------------------------------------------------------


def test_judging_role_without_a_verdict_is_unverified_never_a_pass(client):
    project, run_id, workspace = seed_run_and_workspace(client, key="breaker-no-verdict-run")
    stub = StubRuntime(result={"text": "I looked at things.", "verdict": None,
                               "session_id": "ses_breaker", "tool_calls": 2, "completed": True,
                               "completed_by": "agent", "elapsed_seconds": 12.0,
                               "last_tool": "bash", "budget": {}})
    result = factory.run_agent_stage(stub, run_id, "breaker", "breaking", "attack the invariants",
                                     "Attack the invariants.", workspace, sequence=2,
                                     verdict_required=True)

    assert result["verdict"] is None
    with session() as conn:
        task = conn.execute("SELECT status FROM factory_tasks WHERE id=%s",
                            (result["task_id"],)).fetchone()
        unverified = conn.execute("SELECT event_type FROM factory_events WHERE factory_run_id=%s"
                                  " AND event_type='agent_unverified'", (run_id,)).fetchone()
    assert task["status"] == "unverified"
    assert unverified is not None


def test_judging_role_with_a_pass_verdict_passes(client):
    project, run_id, workspace = seed_run_and_workspace(client, key="breaker-pass-run")
    stub = StubRuntime(result={"text": "All green.\nFACTORY_VERDICT: PASS", "verdict": "PASS",
                               "session_id": "ses_breaker", "tool_calls": 5, "completed": True,
                               "completed_by": "agent", "elapsed_seconds": 30.0,
                               "last_tool": "bash", "budget": {}})
    result = factory.run_agent_stage(stub, run_id, "breaker", "breaking", "attack the invariants",
                                     "Attack the invariants.", workspace, sequence=2,
                                     verdict_required=True)

    with session() as conn:
        task = conn.execute("SELECT status, verdict FROM factory_tasks WHERE id=%s",
                            (result["task_id"],)).fetchone()
    assert result["verdict"] == "PASS"
    assert task["verdict"] == "PASS"
    assert task["status"] == "passed"


# ---------------------------------------------------------------------------
# empty output is a failure, never a completion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["", "   \n\t "])
def test_empty_agent_output_fails_closed_and_is_never_handed_off(client, text):
    """A stalled model can end a session with no text. That is a failed stage."""
    project, run_id, workspace = seed_run_and_workspace(client, key=f"empty-out-{len(text)}-{text.strip()}")
    stub = StubRuntime(result={"text": text, "verdict": None, "session_id": "ses_empty",
                               "tool_calls": 0, "completed": True, "completed_by": "agent",
                               "elapsed_seconds": 302.0, "last_tool": "", "errors": [],
                               "budget": {}})
    result = factory.run_agent_stage(stub, run_id, "architect", "planning", "produce the plan",
                                     "Produce the plan.", workspace, sequence=1,
                                     artifact_path="evidence/plan.md")

    assert result["failed"] is True
    with session() as conn:
        task = conn.execute("SELECT status, error, agent_session_id FROM factory_tasks WHERE id=%s",
                            (result["task_id"],)).fetchone()
        failed = conn.execute("SELECT status, metadata FROM factory_events WHERE factory_run_id=%s"
                              " AND event_type='agent_failed'", (run_id,)).fetchone()
        completed = conn.execute("SELECT count(*) AS n FROM factory_events WHERE factory_run_id=%s"
                                 " AND event_type='agent_completed'", (run_id,)).fetchone()
        handoff = conn.execute("SELECT count(*) AS n FROM factory_events WHERE factory_run_id=%s"
                               " AND event_type='handoff'", (run_id,)).fetchone()

    assert task["status"] == "failed"
    assert "no output" in task["error"]
    assert task["agent_session_id"] == "ses_empty"
    assert failed["status"] == "FAILED"
    assert failed["metadata"]["kind"] == "empty_output"
    assert completed["n"] == 0
    assert handoff["n"] == 0


def test_live_pipeline_stops_when_the_architect_produces_no_output(client):
    """The pipeline must not hand an empty brief to the Builder."""
    project, run_id, workspace = seed_run_and_workspace(client, key="empty-out-pipeline")
    stub = StubRuntime(result={"text": "", "verdict": None, "session_id": "ses_empty",
                               "tool_calls": 0, "completed": True, "completed_by": "agent",
                               "elapsed_seconds": 300.0, "last_tool": "", "errors": [],
                               "budget": {}})
    with pytest.raises(RuntimeError, match="architect produced no output"):
        factory.run_live_pipeline(project["id"], run_id, workspace, stub)

    with session() as conn:
        handoff = conn.execute("SELECT count(*) AS n FROM factory_events WHERE factory_run_id=%s"
                               " AND event_type='handoff'", (run_id,)).fetchone()
        builder = conn.execute("SELECT count(*) AS n FROM factory_tasks WHERE factory_run_id=%s"
                               " AND agent_role='builder'", (run_id,)).fetchone()
    assert handoff["n"] == 0
    assert builder["n"] == 0, "the Builder must never start from an empty hand-off"