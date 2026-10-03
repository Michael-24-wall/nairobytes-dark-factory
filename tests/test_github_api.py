import hashlib
import hmac
import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from app.backend import github_api
from app.backend.db import session
from app.backend.github_service import GitHubConfig, GitHubService

@pytest.fixture(autouse=True)
def deterministic_mode(monkeypatch):
    """Keep these tests hermetic: no LLM calls.

    ``run_factory`` below drives a real factory run. Without this, a reachable
    opencode runtime would make the run select the live-agent pipeline and block
    on agent calls. Live-agent coverage is opt-in elsewhere, exactly as in
    ``tests/test_factory.py``.
    """
    monkeypatch.setenv("FACTORY_EXECUTION_MODE", "deterministic")
    yield


ADMIN_TOKEN = "test-admin-token"
INSTALLATION_ID = 456
REPOSITORY_ID = 99
INSTALLATION_TOKEN = "ghs_fake_installation_token_000111222333"
PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode().replace("\n", "\\n")
CLIENT_SECRET = "fake-client-secret-value"
REPOSITORY = {"id": REPOSITORY_ID, "name": "widget", "full_name": "acme/widget", "private": True, "default_branch": "main", "owner": {"login": "acme", "id": 900, "type": "Organization"}}


class FakeGitHub:
    def __init__(self, target="Organization", repositories=None, pull_number=7, pull_state="open", merged=False):
        self.target = target
        self.repositories = repositories if repositories is not None else [dict(REPOSITORY)]
        self.pull_number = pull_number
        self.pull_state = pull_state
        self.merged = merged
        self.calls: list[tuple[str, str]] = []
        self.pull_request_payload: dict | None = None

    def handler(self, request):
        path = request.url.path
        method = request.method
        self.calls.append((method, path))
        if path.endswith("/access_tokens"):
            return httpx.Response(201, json={"token": INSTALLATION_TOKEN, "expires_at": "2999-01-01T00:00:00Z"})
        if path.startswith("/app/installations/"):
            return httpx.Response(200, json={"id": INSTALLATION_ID, "target_type": self.target, "repository_selection": "all", "account": {"login": "acme", "id": 900, "type": self.target}, "permissions": {"contents": "write", "pull_requests": "write", "metadata": "read"}})
        if path == "/installation/repositories":
            return httpx.Response(200, json={"total_count": len(self.repositories), "repositories": self.repositories})
        if path == "/repos/acme/widget" and method == "GET":
            return httpx.Response(200, json=dict(REPOSITORY))
        if path == "/orgs/acme/repos" and method == "POST":
            created = json.loads(request.read())
            return httpx.Response(201, json={**REPOSITORY, "id": 500, "name": created["name"], "full_name": f"acme/{created['name']}", "html_url": f"https://github.com/acme/{created['name']}"})
        if path == "/repos/acme/widget/pulls" and method == "POST":
            self.pull_request_payload = json.loads(request.read())
            return httpx.Response(201, json={"number": self.pull_number, "html_url": f"https://github.com/acme/widget/pull/{self.pull_number}", "state": "open", "merged": False, "head": {"sha": "c0ffee", "ref": self.pull_request_payload["head"]}, "base": {"ref": self.pull_request_payload["base"]}})
        if path == f"/repos/acme/widget/pulls/{self.pull_number}":
            return httpx.Response(200, json={"number": self.pull_number, "html_url": f"https://github.com/acme/widget/pull/{self.pull_number}", "state": self.pull_state, "merged": self.merged, "draft": False, "mergeable": True, "commits": 1, "changed_files": 6, "additions": 120, "deletions": 0, "head": {"ref": "factory/project/run", "sha": "c0ffee"}, "base": {"ref": "main"}})
        return httpx.Response(404, json={"message": "Not Found"})


@pytest.fixture()
def github_env(monkeypatch, tmp_path):
    remotes = tmp_path / "remotes"
    remotes.mkdir()
    monkeypatch.setenv("FACTORY_ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("GITHUB_APP_ID", "123")
    monkeypatch.setenv("GITHUB_APP_NAME", "nairobytes-factory")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "client-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("GITHUB_PRIVATE_KEY", PRIVATE_KEY)
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "webhook-secret")
    monkeypatch.setenv("GITHUB_REDIRECT_URI", "http://127.0.0.1:5173/settings/github")
    monkeypatch.setenv("GITHUB_INSTALLATION_ID", str(INSTALLATION_ID))
    monkeypatch.setenv("GITHUB_WEB_BASE_URL", remotes.as_uri())
    with session() as conn:
        conn.execute("TRUNCATE github_installations, project_github_integrations, github_pull_requests CASCADE")
    return SimpleNamespace(remotes=remotes, headers={"X-Factory-Admin-Token": ADMIN_TOKEN})


@pytest.fixture()
def fake_github(monkeypatch):
    def install(github: FakeGitHub | None = None):
        github = github or FakeGitHub()
        service = GitHubService(GitHubConfig.from_env(), httpx.Client(transport=httpx.MockTransport(lambda request: github.handler(request)), base_url="https://api.github.com"))
        monkeypatch.setattr(github_api, "_service", lambda: service)
        return github

    return install


@pytest.fixture()
def project(client):
    created = client.post("/projects", json={"name": "GitHub Published Site", "description": "published through the real git flow", "project_type": "Website", "functional_requirements": "Home\nAbout", "technology_preferences": "HTML and CSS"}).json()
    return created


def connect(client, headers, project_id, installation_id=INSTALLATION_ID):
    return client.post(f"/api/github/projects/{project_id}/connect", json={"installation_id": installation_id, "repository_id": REPOSITORY_ID, "owner": "acme", "repository_name": "widget", "default_branch": "main"}, headers=headers)


def bare_remote(remotes: Path) -> Path:
    target = remotes / "acme" / "widget.git"
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--bare", "--quiet", "-b", "main", str(target)], check=True, capture_output=True)
    return target


def git_show(remote: Path, ref: str, path: str) -> str:
    result = subprocess.run(["git", "--git-dir", str(remote), "show", f"{ref}:{path}"], capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else ""


def run_factory(client, project_id, key="github-flow-run"):
    response = client.post("/api/factory/runs", json={"project_id": project_id, "idempotency_key": key})
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    for _ in range(60):
        status = client.get(f"/api/factory/runs/{run_id}").json()
        if status["status"] in {"awaiting_approval", "failed"}:
            break
        time.sleep(0.1)
    assert status["status"] == "awaiting_approval", status
    return run_id


def insert_run(project_id, status="awaiting_approval"):
    with session() as conn:
        return str(conn.execute("INSERT INTO factory_runs (idempotency_key, project_id, status, current_stage) VALUES (%s, %s, %s, %s) RETURNING id", (f"manual-{uuid4()}", project_id, status, status)).fetchone()["id"])


def signature(body: bytes, secret: str = "webhook-secret") -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_every_github_route_requires_the_admin_token(client, github_env, project):
    run_id = insert_run(project["id"])
    unauthorised = [
        client.get("/api/github/status"),
        client.get("/api/github/repositories"),
        client.get("/api/github/installations"),
        client.get(f"/api/github/projects/{project['id']}"),
        client.get("/api/github/webhook"),
        client.post(f"/api/github/projects/{project['id']}/connect", json={"installation_id": 1, "repository_id": 1, "owner": "acme", "repository_name": "widget"}),
        client.delete(f"/api/github/projects/{project['id']}"),
        client.post(f"/api/github/projects/{project['id']}/runs/{run_id}/publish"),
        client.post(f"/api/github/projects/{project['id']}/runs/{run_id}/pull-request"),
        client.get(f"/api/github/projects/{project['id']}/runs/{run_id}/pull-request"),
    ]
    assert [response.status_code for response in unauthorised] == [401] * len(unauthorised)
    assert client.get("/api/github/status", headers={"X-Factory-Admin-Token": "wrong-token"}).status_code == 401


def test_admin_token_that_is_not_configured_is_reported_honestly(client, github_env, monkeypatch):
    monkeypatch.delenv("FACTORY_ADMIN_TOKEN", raising=False)
    response = client.get("/api/github/status")
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_status_reports_not_configured_when_the_app_has_no_credentials(client, github_env, monkeypatch):
    for name in ("GITHUB_APP_ID", "GITHUB_APP_NAME", "GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET", "GITHUB_PRIVATE_KEY", "GITHUB_REDIRECT_URI", "GITHUB_INSTALLATION_ID"):
        monkeypatch.delenv(name, raising=False)
    response = client.get("/api/github/status", headers=github_env.headers)
    assert response.status_code == 503
    assert response.json()["error"] == "GITHUB_NOT_CONFIGURED"


def test_status_reports_the_real_installation_and_its_capabilities(client, github_env, fake_github):
    github = fake_github()
    response = client.get("/api/github/status", headers=github_env.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "CONNECTED"
    assert body["account"] == {"login": "acme", "type": "Organization"}
    assert body["installation_id"] == INSTALLATION_ID
    assert body["repository_count"] == 1
    assert body["permissions"]["contents"] == "write"
    assert body["capabilities"] == {"list_repositories": True, "create_repository": True, "push": True, "pull_requests": True, "webhooks": True}
    assert body["install_url"].endswith("/apps/nairobytes-factory/installations/new")
    assert ("GET", "/app/installations/456") in github.calls


def test_status_reports_not_connected_before_the_app_is_installed(client, github_env, fake_github, monkeypatch):
    monkeypatch.delenv("GITHUB_INSTALLATION_ID", raising=False)
    response = client.get("/api/github/status", headers=github_env.headers)
    body = response.json()
    assert body["status"] == "NOT_CONNECTED"
    assert body["installation_id"] is None
    assert body["install_url"].endswith("/installations/new")
    assert body["capabilities"]["push"] is False


def test_github_responses_never_expose_credentials(client, github_env, fake_github, project):
    fake_github()
    bodies = [
        client.get("/api/github/status", headers=github_env.headers).text,
        client.get("/api/github/repositories", headers=github_env.headers).text,
        client.get("/api/github/installations", headers=github_env.headers).text,
        client.get(f"/api/github/projects/{project['id']}", headers=github_env.headers).text,
        client.get("/api/github/webhook", headers=github_env.headers).text,
    ]
    for body in bodies:
        assert "PRIVATE KEY" not in body
        assert PRIVATE_KEY not in body
        assert CLIENT_SECRET not in body
        assert INSTALLATION_TOKEN not in body
        assert ADMIN_TOKEN not in body


def test_repository_listing_returns_installation_repositories(client, github_env, fake_github):
    fake_github(FakeGitHub(repositories=[dict(REPOSITORY), {**REPOSITORY, "id": 100, "name": "other", "full_name": "acme/other"}]))
    response = client.get("/api/github/repositories", headers=github_env.headers)
    assert response.status_code == 200, response.text
    assert [repo["full_name"] for repo in response.json()["repositories"]] == ["acme/widget", "acme/other"]
    assert response.json()["repositories"][0]["default_branch"] == "main"


def test_repository_listing_is_empty_when_the_installation_has_no_repositories(client, github_env, fake_github):
    fake_github(FakeGitHub(repositories=[]))
    response = client.get("/api/github/repositories", headers=github_env.headers)
    assert response.status_code == 200, response.text
    assert response.json()["repositories"] == []


def test_repository_creation_calls_the_organization_endpoint(client, github_env, fake_github):
    github = fake_github()
    response = client.post("/api/github/repositories", json={"name": "factory-output", "private": True, "description": "created by the factory", "account_login": "acme"}, headers=github_env.headers)
    assert response.status_code == 201, response.text
    assert response.json()["full_name"] == "acme/factory-output"
    assert ("POST", "/orgs/acme/repos") in github.calls


def test_repository_creation_is_refused_for_personal_installations(client, github_env, fake_github):
    fake_github(FakeGitHub(target="User"))
    response = client.post("/api/github/repositories", json={"name": "factory-output", "private": True, "account_login": "acme"}, headers=github_env.headers)
    assert response.status_code == 422
    assert response.json()["error"] == "GITHUB_UNPROCESSABLE"
    assert "organization" in response.json()["message"]


def test_repository_creation_rejects_names_that_are_not_github_names(client, github_env, fake_github):
    fake_github()
    response = client.post("/api/github/repositories", json={"name": "../../etc/passwd", "account_login": "acme"}, headers=github_env.headers)
    assert response.status_code == 422


def test_project_mapping_rejects_arbitrary_github_paths(client, github_env, fake_github, project):
    fake_github()
    for owner, name in (("../../etc", "passwd"), ("acme", "widget/../../secrets"), ("acme", "-bad-start")):
        response = client.post(f"/api/github/projects/{project['id']}/connect", json={"installation_id": INSTALLATION_ID, "repository_id": REPOSITORY_ID, "owner": owner, "repository_name": name}, headers=github_env.headers)
        assert response.status_code == 422, (owner, name, response.text)


def test_connect_persists_installation_repository_and_default_branch(client, github_env, fake_github, project):
    fake_github()
    response = connect(client, github_env.headers, project["id"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["owner"] == "acme"
    assert body["repository_name"] == "widget"
    assert body["default_branch"] == "main"
    assert body["status"] == "connected"
    with session() as conn:
        installation = conn.execute("SELECT account_login, account_type, status FROM github_installations WHERE installation_id=%s", (INSTALLATION_ID,)).fetchone()
    assert installation == {"account_login": "acme", "account_type": "Organization", "status": "connected"}


def test_connect_rejects_a_repository_identity_mismatch(client, github_env, fake_github, project):
    fake_github()
    response = client.post(f"/api/github/projects/{project['id']}/connect", json={"installation_id": INSTALLATION_ID, "repository_id": 1234, "owner": "acme", "repository_name": "widget"}, headers=github_env.headers)
    assert response.status_code == 409
    assert response.json()["error"] == "GITHUB_REPOSITORY_MISMATCH"


def test_connect_reports_a_repository_missing_from_the_installation(client, github_env, fake_github, project):
    fake_github()

    def handler(request):
        if request.url.path == "/repos/acme/deleted-repo":
            return httpx.Response(404, json={"message": "Not Found"})
        return FakeGitHub().handler(request)

    github = fake_github()
    github.handler = handler
    response = client.post(f"/api/github/projects/{project['id']}/connect", json={"installation_id": INSTALLATION_ID, "repository_id": REPOSITORY_ID, "owner": "acme", "repository_name": "deleted-repo"}, headers=github_env.headers)
    assert response.status_code == 404
    assert response.json()["error"] == "GITHUB_NOT_FOUND"


def test_connect_reports_an_unknown_project(client, github_env, fake_github):
    fake_github()
    response = connect(client, github_env.headers, "3f6b4a6e-0000-4000-8000-000000000000")
    assert response.status_code == 404


def test_one_project_cannot_read_another_projects_github_state(client, github_env, fake_github):
    fake_github()
    first = client.post("/projects", json={"name": "First Linked Project", "project_type": "Website"}).json()
    second = client.post("/projects", json={"name": "Second Unlinked Project", "project_type": "Website"}).json()
    assert connect(client, github_env.headers, first["id"]).status_code == 200
    linked = client.get(f"/api/github/projects/{first['id']}", headers=github_env.headers).json()
    other = client.get(f"/api/github/projects/{second['id']}", headers=github_env.headers).json()
    assert linked["linked"] is True and linked["mapping"]["repository_name"] == "widget"
    assert other["linked"] is False and other["mapping"] is None
    assert client.get(f"/api/github/projects/{first['id']}").status_code == 401
    assert client.delete(f"/api/github/projects/{first['id']}").status_code == 401


def test_publish_rejects_runs_that_are_not_verified(client, github_env, fake_github, project):
    fake_github()
    assert connect(client, github_env.headers, project["id"]).status_code == 200
    run_id = insert_run(project["id"], status="building")
    response = client.post(f"/api/github/projects/{project['id']}/runs/{run_id}/publish", headers=github_env.headers)
    assert response.status_code == 409
    assert response.json()["error"] == "GITHUB_RUN_NOT_PUBLISHABLE"


def test_publish_requires_a_linked_repository(client, github_env, fake_github, project):
    fake_github()
    run_id = insert_run(project["id"])
    response = client.post(f"/api/github/projects/{project['id']}/runs/{run_id}/publish", headers=github_env.headers)
    assert response.status_code == 409
    assert "not linked" in response.json()["detail"]


def test_pull_request_requires_a_published_run(client, github_env, fake_github, project):
    fake_github()
    assert connect(client, github_env.headers, project["id"]).status_code == 200
    run_id = insert_run(project["id"])
    response = client.post(f"/api/github/projects/{project['id']}/runs/{run_id}/pull-request", headers=github_env.headers)
    assert response.status_code == 409
    assert response.json()["error"] == "GITHUB_NOT_PUBLISHED"


def test_publish_pushes_real_files_and_opens_a_real_pull_request(client, github_env, fake_github, project):
    github = fake_github()
    remote = bare_remote(github_env.remotes)
    run_id = run_factory(client, project["id"])
    assert connect(client, github_env.headers, project["id"]).status_code == 200

    published = client.post(f"/api/github/projects/{project['id']}/runs/{run_id}/publish", headers=github_env.headers)
    assert published.status_code == 200, published.text
    push = published.json()
    assert push["status"] == "PUSHED"
    assert push["branch"] == f"factory/project-{project['id']}/run-{run_id}"
    assert push["base_branch"] == "main"
    assert len(push["commit"]) == 40
    assert "index.html" in push["files_changed"]
    assert "architecture/architecture.md" in push["files_changed"]
    assert "tests/test_generated_site.py" in push["files_changed"]
    assert "evidence/breaker_report.md" in push["files_changed"]

    heads = subprocess.run(["git", "ls-remote", "--heads", str(remote)], capture_output=True, text=True).stdout
    assert f"refs/heads/{push['branch']}" in heads
    assert "GitHub Published Site" in git_show(remote, push["branch"], "index.html")
    assert git_show(remote, "main", "index.html") == ""

    pull = client.post(f"/api/github/projects/{project['id']}/runs/{run_id}/pull-request", headers=github_env.headers)
    assert pull.status_code == 201, pull.text
    created = pull.json()
    assert created["number"] == 7
    assert created["url"] == "https://github.com/acme/widget/pull/7"
    assert created["status"] == "open"

    payload = github.pull_request_payload
    assert payload["head"] == push["branch"]
    assert payload["base"] == "main"
    assert "GitHub Published Site" in payload["body"]
    assert "### Tests executed by the factory" in payload["body"]
    assert "### Breaker result" in payload["body"]
    assert "### Verifier result" in payload["body"]
    assert "### Known limitations" in payload["body"]
    assert "Deployment is NOT CONFIGURED" in payload["body"]
    assert PRIVATE_KEY not in payload["body"] and INSTALLATION_TOKEN not in payload["body"]

    with session() as conn:
        stored = conn.execute("SELECT * FROM github_pull_requests WHERE project_id=%s", (project["id"],)).fetchall()
        commit = conn.execute("SELECT commit_hash, branch, remote_url FROM git_commits WHERE project_id=%s AND remote_url IS NOT NULL", (project["id"],)).fetchone()
        event = conn.execute("SELECT event_type FROM factory_events WHERE factory_run_id=%s AND event_type='github_pull_request'", (run_id,)).fetchone()
    assert len(stored) == 1
    assert commit["commit_hash"] == push["commit"] and commit["branch"] == push["branch"]
    assert event is not None

    state = client.get(f"/api/github/projects/{project['id']}", headers=github_env.headers).json()
    assert state["linked"] is True
    assert state["mapping"]["default_branch"] == "main"
    assert state["latest_run"]["id"] == run_id
    assert state["commits"][0]["commit_hash"] == push["commit"]
    assert state["pull_requests"][0]["number"] == 7


def test_pull_request_status_is_read_back_from_github(client, github_env, fake_github, project):
    fake_github()
    bare_remote(github_env.remotes)
    run_id = run_factory(client, project["id"])
    assert connect(client, github_env.headers, project["id"]).status_code == 200
    assert client.post(f"/api/github/projects/{project['id']}/runs/{run_id}/publish", headers=github_env.headers).status_code == 200
    assert client.post(f"/api/github/projects/{project['id']}/runs/{run_id}/pull-request", headers=github_env.headers).status_code == 201

    merged_github = fake_github(FakeGitHub(pull_state="closed", merged=True))
    refreshed = client.get(f"/api/github/projects/{project['id']}/runs/{run_id}/pull-request", headers=github_env.headers)
    assert refreshed.status_code == 200, refreshed.text
    body = refreshed.json()
    assert body["state"] == "closed"
    assert body["merged"] is True
    assert body["status"] == "merged"
    assert body["changed_files"] == 6
    assert ("GET", "/repos/acme/widget/pulls/7") in merged_github.calls


def test_pull_request_status_reports_a_deleted_pull_request(client, github_env, fake_github, project):
    fake_github()
    bare_remote(github_env.remotes)
    run_id = run_factory(client, project["id"])
    connect(client, github_env.headers, project["id"])
    client.post(f"/api/github/projects/{project['id']}/runs/{run_id}/publish", headers=github_env.headers)
    client.post(f"/api/github/projects/{project['id']}/runs/{run_id}/pull-request", headers=github_env.headers)
    fake_github(FakeGitHub(pull_number=999))
    response = client.get(f"/api/github/projects/{project['id']}/runs/{run_id}/pull-request", headers=github_env.headers)
    assert response.status_code == 404
    assert response.json()["error"] == "GITHUB_NOT_FOUND"


def test_disconnect_removes_the_project_link(client, github_env, fake_github, project):
    fake_github()
    connect(client, github_env.headers, project["id"])
    removed = client.delete(f"/api/github/projects/{project['id']}", headers=github_env.headers)
    assert removed.status_code == 200
    assert removed.json()["status"] == "disconnected"
    assert client.get(f"/api/github/projects/{project['id']}", headers=github_env.headers).json()["linked"] is False
    assert client.delete(f"/api/github/projects/{project['id']}", headers=github_env.headers).status_code == 404


def test_revoked_installation_token_is_reported_as_a_credential_failure(client, github_env, fake_github, project):
    github = fake_github()

    def handler(request):
        if request.url.path.endswith("/access_tokens"):
            return httpx.Response(201, json={"token": INSTALLATION_TOKEN, "expires_at": "2999-01-01T00:00:00Z"})
        if request.url.path == "/installation/repositories":
            return httpx.Response(403, json={"message": "Resource not accessible by integration"})
        return github.handler(request)

    github.handler = handler
    response = client.get("/api/github/repositories", headers=github_env.headers)
    assert response.status_code == 502
    assert response.json()["error"] == "GITHUB_FORBIDDEN"
    assert ADMIN_TOKEN not in response.text


def test_github_timeouts_are_reported_as_gateway_timeouts(client, github_env, fake_github):
    github = fake_github()

    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)

    github.handler = handler
    response = client.get("/api/github/status", headers=github_env.headers)
    assert response.status_code == 504
    assert response.json()["error"] == "GITHUB_TIMEOUT"


def test_github_failures_never_expose_stack_traces(client, github_env, fake_github):
    github = fake_github()

    def handler(request):
        if request.url.path.endswith("/access_tokens"):
            return httpx.Response(201, json={"token": INSTALLATION_TOKEN, "expires_at": "2999-01-01T00:00:00Z"})
        return httpx.Response(500, json={"message": "Server Error", "documentation_url": "https://docs.github.com/rest", "stack": "internal-host-9f2"})

    github.handler = handler
    response = client.get("/api/github/repositories", headers=github_env.headers)
    assert response.status_code == 502
    assert response.json()["error"] == "GITHUB_SERVER_ERROR"
    assert "Traceback" not in response.text and "internal-host" not in response.text


def test_webhook_rejects_requests_when_no_secret_is_configured(client, github_env, monkeypatch):
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    response = client.post("/api/github/webhook", json={"action": "created"})
    assert response.status_code == 503
    assert response.json()["error"] == "GITHUB_WEBHOOK_NOT_CONFIGURED"


def test_webhook_rejects_an_invalid_signature(client, github_env):
    body = json.dumps({"action": "created", "installation": {"id": INSTALLATION_ID, "account": {"login": "acme", "id": 900, "type": "Organization"}}}).encode()
    response = client.post("/api/github/webhook", content=body, headers={"Content-Type": "application/json", "X-GitHub-Event": "installation", "X-Hub-Signature-256": signature(b"other-body")})
    assert response.status_code == 401
    assert response.json()["error"] == "GITHUB_WEBHOOK_SIGNATURE_INVALID"
    with session() as conn:
        assert conn.execute("SELECT count(*) AS count FROM github_installations").fetchone()["count"] == 0


def test_webhook_records_a_new_installation_and_status_uses_it(client, github_env, fake_github, monkeypatch):
    monkeypatch.delenv("GITHUB_INSTALLATION_ID", raising=False)
    body = json.dumps({"action": "created", "installation": {"id": 777, "account": {"login": "acme", "id": 900, "type": "Organization"}}}).encode()
    response = client.post("/api/github/webhook", content=body, headers={"Content-Type": "application/json", "X-GitHub-Event": "installation", "X-Hub-Signature-256": signature(body)})
    assert response.status_code == 200, response.text
    assert response.json()["installation_status"] == "connected"
    with session() as conn:
        stored = conn.execute("SELECT installation_id, account_login, status FROM github_installations").fetchone()
    assert stored["installation_id"] == 777 and stored["status"] == "connected"

    github = fake_github()
    status = client.get("/api/github/status", headers=github_env.headers)
    assert status.json()["status"] == "CONNECTED"
    assert ("GET", "/app/installations/777") in github.calls


def test_webhook_marks_an_uninstalled_app_as_disconnected(client, github_env):
    created = json.dumps({"action": "created", "installation": {"id": 888, "account": {"login": "acme", "id": 900, "type": "Organization"}}}).encode()
    client.post("/api/github/webhook", content=created, headers={"Content-Type": "application/json", "X-GitHub-Event": "installation", "X-Hub-Signature-256": signature(created)})
    removed = json.dumps({"action": "deleted", "installation": {"id": 888, "account": {"login": "acme", "id": 900, "type": "Organization"}}}).encode()
    response = client.post("/api/github/webhook", content=removed, headers={"Content-Type": "application/json", "X-GitHub-Event": "installation", "X-Hub-Signature-256": signature(removed)})
    assert response.json()["installation_status"] == "disconnected"
    with session() as conn:
        assert conn.execute("SELECT status FROM github_installations WHERE installation_id=888").fetchone()["status"] == "disconnected"


def test_webhook_updates_the_stored_pull_request_state(client, github_env, fake_github, project):
    fake_github()
    bare_remote(github_env.remotes)
    run_id = run_factory(client, project["id"])
    connect(client, github_env.headers, project["id"])
    client.post(f"/api/github/projects/{project['id']}/runs/{run_id}/publish", headers=github_env.headers)
    client.post(f"/api/github/projects/{project['id']}/runs/{run_id}/pull-request", headers=github_env.headers)

    body = json.dumps({"action": "closed", "repository": {"name": "widget", "owner": {"login": "acme"}}, "pull_request": {"number": 7, "state": "closed", "merged": True}}).encode()
    response = client.post("/api/github/webhook", content=body, headers={"Content-Type": "application/json", "X-GitHub-Event": "pull_request", "X-Hub-Signature-256": signature(body)})
    assert response.json()["status"] == "RECORDED"
    assert response.json()["pull_request_status"] == "merged"
    with session() as conn:
        assert conn.execute("SELECT status FROM github_pull_requests WHERE number=7").fetchone()["status"] == "merged"


def test_webhook_ignores_unknown_events_and_answers_pings(client, github_env):
    ping = b'{"zen":"Keep it logically awesome."}'
    assert client.post("/api/github/webhook", content=ping, headers={"Content-Type": "application/json", "X-GitHub-Event": "ping", "X-Hub-Signature-256": signature(ping)}).json()["status"] == "PONG"
    unknown = b'{"zen":"unknown"}'
    assert client.post("/api/github/webhook", content=unknown, headers={"Content-Type": "application/json", "X-GitHub-Event": "star", "X-Hub-Signature-256": signature(unknown)}).json()["status"] == "IGNORED"