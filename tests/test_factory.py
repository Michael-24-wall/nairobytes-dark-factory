import time

import pytest

from api_helpers import seed_table
from app.backend.db import session


@pytest.fixture(autouse=True)
def deterministic_mode(monkeypatch):
    """Keep CI hermetic: no LLM calls. Live-agent coverage is opt-in elsewhere."""
    monkeypatch.setenv("FACTORY_EXECUTION_MODE", "deterministic")
    yield


def project_payload():
    return {
        "name": "Generated Factory Site",
        "description": "A generated website workload.",
        "project_type": "Website",
        "functional_requirements": "Home\nAbout\nContact",
        "nonfunctional_requirements": "Responsive",
        "technology_preferences": "HTML and CSS",
    }


def _await_terminal(client, run_id):
    for _ in range(80):
        status = client.get(f"/api/factory/runs/{run_id}").json()
        if status["status"] in {"awaiting_approval", "failed", "approved"}:
            return status
        time.sleep(0.1)
    return status


def test_factory_run_generates_artifacts_tests_and_real_git_commit(client):
    project = client.post("/projects", json=project_payload()).json()
    response = client.post("/api/factory/runs", json={"project_id": project["id"], "idempotency_key": "factory-test-run"})
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]

    status = _await_terminal(client, run_id)
    assert status["status"] == "awaiting_approval", status
    events = client.get(f"/api/factory/runs/{run_id}/events").json()
    tasks = client.get(f"/api/factory/runs/{run_id}/tasks").json()
    assert {event["stage"] for event in events} >= {"planning", "building", "testing", "breaking", "retesting", "verifying", "awaiting_approval"}
    assert {task["agent_role"] for task in tasks} >= {"architect", "builder", "tester", "breaker", "verifier"}

    with session() as conn:
        artifacts = conn.execute("SELECT path FROM factory_artifacts WHERE factory_run_id=%s", (run_id,)).fetchall()
        commit = conn.execute("SELECT commit_hash FROM git_commits WHERE factory_run_id=%s", (run_id,)).fetchone()
        approval = conn.execute("SELECT status FROM approvals WHERE factory_run_id=%s", (run_id,)).fetchone()
    assert "architecture/architecture.md" in {row["path"] for row in artifacts}
    assert commit["commit_hash"]
    assert approval["status"] == "PENDING"

    approved = client.post(f"/api/factory/runs/{run_id}/approve", json={"reason": "Reviewed generated artifact."})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"


def test_factory_run_idempotency_returns_existing_run(client):
    project = client.post("/projects", json=project_payload()).json()
    first = client.post("/api/factory/runs", json={"project_id": project["id"], "idempotency_key": "same-factory-run"})
    second = client.post("/api/factory/runs", json={"project_id": project["id"], "idempotency_key": "same-factory-run"})
    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["id"] == first.json()["id"]


def test_run_records_execution_mode_and_declares_it(client):
    project = client.post("/projects", json=project_payload()).json()
    run_id = client.post("/api/factory/runs", json={"project_id": project["id"], "idempotency_key": "mode-run"}).json()["id"]
    _await_terminal(client, run_id)
    events = client.get(f"/api/factory/runs/{run_id}/events").json()
    selection = [event for event in events if event["event_type"] == "execution_mode_selected"]
    assert selection, events
    assert "deterministic" in selection[0]["message"]


def test_timeline_exposes_handoff_chain_and_approval(client):
    project = client.post("/projects", json=project_payload()).json()
    run_id = client.post("/api/factory/runs", json={"project_id": project["id"], "idempotency_key": "timeline-run"}).json()["id"]
    _await_terminal(client, run_id)

    timeline = client.get(f"/api/factory/runs/{run_id}/timeline").json()
    assert timeline["execution_mode"] == "deterministic"
    assert timeline["approval"]["status"] == "PENDING"
    roles = [task["agent_role"] for task in timeline["tasks"]]
    assert roles.index("architect") < roles.index("builder") < roles.index("verifier")
    assert all(task["sequence"] > 0 for task in timeline["tasks"])
    assert {artifact["artifact_type"] for artifact in timeline["artifacts"]} >= {"architecture", "generated_source"}


def test_timeline_records_explicit_agent_to_agent_handoffs(client):
    """The REAL RECORD chain: every stage names the agent it hands off to."""
    project = client.post("/projects", json=project_payload()).json()
    run_id = client.post("/api/factory/runs", json={"project_id": project["id"], "idempotency_key": "handoff-chain-run"}).json()["id"]
    _await_terminal(client, run_id)

    timeline = client.get(f"/api/factory/runs/{run_id}/timeline").json()
    messages = [handoff["message"] for handoff in timeline["handoffs"]]
    assert messages == [
        "Architect finished and handed off to Builder. The templated plan is ready for implementation.",
        "Builder finished and handed off to Tester. Generated site files are ready for the test gate.",
        "Tester finished and handed off to Breaker. The generated suite passed; the breaker now attacks it.",
        "Breaker finished and handed off to Tester. Breaker PASS; handing back to the tester for the retest gate.",
        "Tester finished and handed off to Verifier. The retest gate passed; independent verification begins.",
        "Verifier finished and handed off to Human. Independent verification passed; human approval is required.",
    ]

    pairs = [(entry["from_role"], entry["to_role"]) for entry in timeline["handoffs"]]
    assert pairs == [
        ("architect", "builder"),
        ("builder", "tester"),
        ("tester", "breaker"),
        ("breaker", "tester"),
        ("tester", "verifier"),
        ("verifier", "human"),
    ]
    assert all(entry["status"] == "COMPLETED" for entry in timeline["handoffs"])

    # The rich event stream is real: run_started + handoffs with source/destination agents.
    event_types = {event["event_type"] for event in timeline["events"]}
    assert "run_started" in event_types
    handoff_events = [event for event in timeline["events"] if event["event_type"] == "handoff"]
    assert handoff_events
    assert all(event["source_agent"] and event["destination_agent"] for event in handoff_events)

    handed = {task["agent_role"]: task["handed_to"] for task in timeline["tasks"]}
    assert handed["architect"] == "builder"
    assert handed["builder"] == "tester"
    assert handed["breaker"] == "tester"
    assert handed["verifier"] == "human"


def test_runtime_endpoint_reports_availability_without_agents(client):
    payload = client.get("/api/factory/runtime").json()
    assert isinstance(payload["available"], bool)
    assert payload["model_id"]
    assert payload["roles"] == ["architect", "builder", "breaker", "repair", "verifier"]
    assert payload["max_repair_rounds"] >= 1


def test_failed_run_records_error_and_terminal_state(client, monkeypatch):
    monkeypatch.setenv("FACTORY_MAX_REPAIR_ROUNDS", "0")
    project = client.post("/projects", json=project_payload()).json()
    run_id = client.post("/api/factory/runs", json={"project_id": project["id"], "idempotency_key": "fail-run"}).json()["id"]
    status = _await_terminal(client, run_id)
    assert status["status"] in {"awaiting_approval", "failed"}
    if status["status"] == "failed":
        assert status["error"]
        events = client.get(f"/api/factory/runs/{run_id}/events").json()
        assert any(event["event_type"] == "run_failed" for event in events)