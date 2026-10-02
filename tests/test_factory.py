import time

from api_helpers import seed_table
from app.backend.db import session


def project_payload():
    return {
        "name": "Generated Factory Site",
        "description": "A generated website workload.",
        "project_type": "Website",
        "functional_requirements": "Home\nAbout\nContact",
        "nonfunctional_requirements": "Responsive",
        "technology_preferences": "HTML and CSS",
    }


def test_factory_run_generates_artifacts_tests_and_real_git_commit(client):
    project = client.post("/projects", json=project_payload()).json()
    response = client.post("/api/factory/runs", json={"project_id": project["id"], "idempotency_key": "factory-test-run"})
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]

    for _ in range(40):
        status = client.get(f"/api/factory/runs/{run_id}").json()
        if status["status"] in {"awaiting_approval", "failed"}:
            break
        time.sleep(0.1)

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