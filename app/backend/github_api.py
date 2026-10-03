import json
import os
import secrets
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from .db import session
from .factory import workspace_for
from .git_flow import GitFlowError, GitPublisher, factory_branch
from .github_service import GitHubConfig, GitHubError, GitHubService, verify_webhook_signature

router = APIRouter(prefix="/api/github", tags=["github"])

NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$"
BRANCH_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$"
PUBLISHABLE_RUN_STATES = {"awaiting_approval", "approved"}
MAX_WEBHOOK_BYTES = 2_000_000


class RepositoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=NAME_PATTERN)
    private: bool = True
    description: str = Field(default="", max_length=5000)
    account_login: str | None = Field(default=None, pattern=NAME_PATTERN)


class ProjectMapping(BaseModel):
    installation_id: int = Field(gt=0)
    repository_id: int = Field(gt=0)
    owner: str = Field(min_length=1, max_length=100, pattern=NAME_PATTERN)
    repository_name: str = Field(min_length=1, max_length=100, pattern=NAME_PATTERN)
    default_branch: str = Field(default="main", min_length=1, max_length=200, pattern=BRANCH_PATTERN)


def _admin_token(token: str | None):
    expected = os.environ.get("FACTORY_ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="admin authentication is not configured")
    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="invalid admin authentication")


def _fail(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message})


def _github_failure(error: GitHubError) -> JSONResponse:
    return _fail(error.http_status, error.code, str(error))


def _git_failure(error: GitFlowError) -> JSONResponse:
    return _fail(502, error.code, str(error))


def _service() -> GitHubService:
    return GitHubService()


def _require_configuration(service: GitHubService) -> JSONResponse | None:
    if not service.config.configured:
        return _fail(503, "GITHUB_NOT_CONFIGURED", "the GitHub App is not configured on this server")
    return None


def _out(row: dict) -> dict:
    return {
        key: str(value) if isinstance(value, UUID) else value.isoformat() if key.endswith("_at") and hasattr(value, "isoformat") else value
        for key, value in row.items()
    }


def _latest_installation_id(conn) -> str:
    stored = conn.execute("SELECT installation_id FROM github_installations WHERE status='connected' ORDER BY connected_at DESC LIMIT 1").fetchone()
    if stored:
        return str(stored["installation_id"])
    return ""


def _require_mapping(conn, project_id: UUID) -> dict:
    row = conn.execute(
        "SELECT i.*, g.account_login, g.account_type FROM project_github_integrations i"
        " JOIN github_installations g ON g.installation_id = i.installation_id"
        " WHERE i.project_id = %s",
        (project_id,),
    ).fetchone()
    if row is None or row["status"] != "connected":
        raise HTTPException(status_code=409, detail="project is not linked to a GitHub repository")
    return dict(row)


def _single_line(value: Any, limit: int = 400) -> str:
    text = " ".join(str(value or "").split())
    return text[-limit:] if text else ""


def _task_line(task: dict) -> str:
    summary = _single_line(task.get("output") or task.get("error") or "", 300)
    return f"- `{task['agent_role']}` / `{task['task_type']}`: **{task['status']}**" + (f" - `{summary}`" if summary else " - no recorded output")


def _pull_request_body(project: dict, run: dict, tasks: list[dict], artifacts: list[dict], push: dict, approval_status: str) -> str:
    roles = {task["agent_role"] for task in tasks}
    tester_lines = [_task_line(task) for task in tasks if task["agent_role"] == "tester"]
    breaker_lines = [_task_line(task) for task in tasks if task["agent_role"] == "breaker"]
    verifier_lines = [_task_line(task) for task in tasks if task["agent_role"] == "verifier"]
    files = push.get("files_changed") or []
    lines = [
        "## Nairobytes Dark Factory",
        "",
        f"**Project:** {project['name']} (`{project['slug']}`)",
        f"**Factory run:** `{run['id']}`",
        f"**Run status when published:** `{run['status']}`",
        f"**Human approval:** `{approval_status}`",
        f"**Factory branch:** `{push.get('branch')}`",
        f"**Base branch:** `{push.get('base_branch')}`",
        f"**Commit:** `{push.get('commit')}`",
        "",
        "### Files changed",
        "",
        *( [f"- `{name}`" for name in files] or ["- No file changes were published."] ),
        "",
        "### Tests executed by the factory",
        "",
        *(tester_lines or ["- No tester execution was recorded for this run."]),
        "",
        "### Breaker result",
        "",
        *(breaker_lines or ["- No Breaker task was recorded for this run."]),
        "",
        "### Verifier result",
        "",
        *(verifier_lines or ["- No Verifier task was recorded for this run."]),
        "",
        "### Evidence recorded by the factory",
        "",
        *( [f"- `{artifact['path']}` ({artifact['artifact_type']})" for artifact in artifacts] or ["- No evidence artifacts were recorded for this run."] ),
        "",
        "### Known limitations",
        "",
        "- Deployment is NOT CONFIGURED in this environment; the Dark Factory did not deploy anything.",
        "- The only tests executed by the factory are the generated project's own pytest suite recorded in the run output above.",
        "- No dependency audit, container build, or CI workflow was executed by the Dark Factory for this run.",
        "- Branch protection, required reviews, and the merge decision are enforced by the repository settings and by a human reviewer on GitHub.",
    ]
    if "breaker" not in roles:
        lines.append("- This run has no Breaker task, so no adversarial result is claimed.")
    if "verifier" not in roles:
        lines.append("- This run has no Verifier task, so no independent verification is claimed.")
    if push.get("seeded_base_branch"):
        lines.append("- The repository was empty, so the Dark Factory created an initial commit on the base branch before opening this pull request.")
    lines.append("")
    lines.append("Generated by the Nairobytes Dark Factory from recorded run evidence only.")
    return "\n".join(lines)


def _generated_files(conn, project_id: UUID, run_id: UUID) -> dict[str, bytes]:
    workspace = workspace_for(conn, project_id)
    rows = conn.execute("SELECT path FROM factory_artifacts WHERE factory_run_id=%s ORDER BY path", (run_id,)).fetchall()
    files: dict[str, bytes] = {}
    for row in rows:
        candidate = (workspace / row["path"]).resolve()
        if workspace not in candidate.parents or not candidate.is_file():
            continue
        files[row["path"]] = candidate.read_bytes()
    return files


@router.get("/status")
def github_status(x_factory_admin_token: str | None = Header(default=None)):
    _admin_token(x_factory_admin_token)
    service = _service()
    blocked = _require_configuration(service)
    if blocked:
        return blocked
    with session() as conn:
        installation_id = service.config.installation_id or _latest_installation_id(conn)
    install_url = service.config.install_url
    if not installation_id:
        return {
            "status": "NOT_CONNECTED",
            "app_name": service.config.app_name,
            "app_slug": service.config.slug,
            "install_url": install_url,
            "installation_id": None,
            "account": None,
            "repository_count": 0,
            "capabilities": {"list_repositories": False, "create_repository": False, "push": False, "pull_requests": False, "webhooks": bool(service.config.webhook_secret)},
            "message": "No GitHub App installation is recorded. Install the App on GitHub and return here.",
        }
    try:
        installation = service.installation(installation_id)
        repositories = service.repositories(installation_id)
    except GitHubError as error:
        return _github_failure(error)
    account = installation.get("account") or {}
    permissions = installation.get("permissions") or {}
    target_type = str(installation.get("target_type") or account.get("type") or "")
    return {
        "status": "CONNECTED",
        "app_name": service.config.app_name,
        "app_slug": service.config.slug,
        "install_url": install_url,
        "installation_id": installation.get("id"),
        "account": {"login": account.get("login"), "type": target_type or "Unknown"},
        "repository_count": len(repositories),
        "repository_selection": installation.get("repository_selection"),
        "permissions": {key: permissions.get(key) for key in ("contents", "pull_requests", "metadata", "administration") if key in permissions},
        "capabilities": {
            "list_repositories": True,
            "create_repository": target_type.lower() == "organization",
            "push": str(permissions.get("contents", "")).lower() in {"write", "admin"},
            "pull_requests": str(permissions.get("pull_requests", "")).lower() in {"write", "admin"},
            "webhooks": bool(service.config.webhook_secret),
        },
        "message": "GitHub App installation responded.",
    }


@router.get("/installations")
def list_installations(x_factory_admin_token: str | None = Header(default=None)):
    _admin_token(x_factory_admin_token)
    with session() as conn:
        rows = conn.execute("SELECT * FROM github_installations ORDER BY connected_at DESC").fetchall()
    return {"installations": [_out(row) for row in rows]}


@router.get("/repositories")
def list_github_repositories(x_factory_admin_token: str | None = Header(default=None)):
    _admin_token(x_factory_admin_token)
    service = _service()
    blocked = _require_configuration(service)
    if blocked:
        return blocked
    try:
        with session() as conn:
            installation_id = service.config.installation_id or _latest_installation_id(conn)
        repositories = service.repositories(installation_id or None)
    except GitHubError as error:
        return _github_failure(error)
    return {
        "repositories": [
            {
                "id": repo.get("id"),
                "name": repo.get("name"),
                "full_name": repo.get("full_name"),
                "owner": (repo.get("owner") or {}).get("login"),
                "private": repo.get("private"),
                "default_branch": repo.get("default_branch"),
                "archived": repo.get("archived"),
                "permissions": repo.get("permissions"),
            }
            for repo in repositories
        ]
    }


@router.post("/repositories", status_code=201)
def create_github_repository(body: RepositoryCreate, x_factory_admin_token: str | None = Header(default=None)):
    _admin_token(x_factory_admin_token)
    service = _service()
    blocked = _require_configuration(service)
    if blocked:
        return blocked
    try:
        with session() as conn:
            installation_id = service.config.installation_id or _latest_installation_id(conn)
        repository = service.create_repository(body.name, body.private, body.description, body.account_login, installation_id or None)
    except GitHubError as error:
        return _github_failure(error)
    return {
        "id": repository.get("id"),
        "name": repository.get("name"),
        "full_name": repository.get("full_name"),
        "owner": (repository.get("owner") or {}).get("login"),
        "private": repository.get("private"),
        "default_branch": repository.get("default_branch"),
        "html_url": repository.get("html_url"),
    }


@router.get("/projects/{project_id}")
def project_github_state(project_id: UUID, x_factory_admin_token: str | None = Header(default=None)):
    _admin_token(x_factory_admin_token)
    with session() as conn:
        if conn.execute("SELECT id FROM projects WHERE id=%s", (project_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="project not found")
        mapping = conn.execute(
            "SELECT i.*, g.account_login, g.account_type FROM project_github_integrations i"
            " JOIN github_installations g ON g.installation_id = i.installation_id WHERE i.project_id=%s",
            (project_id,),
        ).fetchone()
        run = conn.execute("SELECT * FROM factory_runs WHERE project_id=%s ORDER BY created_at DESC LIMIT 1", (project_id,)).fetchone()
        commits = conn.execute(
            "SELECT branch, base_branch, commit_hash, message, remote_url, files_changed, created_at, pushed_at FROM git_commits WHERE project_id=%s ORDER BY created_at DESC",
            (project_id,),
        ).fetchall()
        pull_requests = conn.execute(
            "SELECT number, url, title, status, source_branch, target_branch, factory_run_id, created_at, updated_at FROM github_pull_requests WHERE project_id=%s ORDER BY created_at DESC",
            (project_id,),
        ).fetchall()
    return {
        "linked": mapping is not None and mapping["status"] == "connected",
        "mapping": _out(dict(mapping)) if mapping else None,
        "latest_run": _out(dict(run)) if run else None,
        "commits": [_out(dict(row)) for row in commits],
        "pull_requests": [_out(dict(row)) for row in pull_requests],
    }


@router.post("/projects/{project_id}/connect")
def connect_project_repository(project_id: UUID, body: ProjectMapping, x_factory_admin_token: str | None = Header(default=None)):
    _admin_token(x_factory_admin_token)
    service = _service()
    blocked = _require_configuration(service)
    if blocked:
        return blocked
    try:
        repository = service.repository(body.owner, body.repository_name, str(body.installation_id))
    except GitHubError as error:
        return _github_failure(error)
    if int(repository.get("id", 0)) != body.repository_id:
        return _fail(409, "GITHUB_REPOSITORY_MISMATCH", "repository identity did not match GitHub")
    owner = repository.get("owner") or {}
    default_branch = repository.get("default_branch") or body.default_branch
    with session() as conn:
        if conn.execute("SELECT id FROM projects WHERE id=%s", (project_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="project not found")
        conn.execute(
            "INSERT INTO github_installations (installation_id, account_id, account_login, account_type, status) VALUES (%s, %s, %s, %s, 'connected')"
            " ON CONFLICT (installation_id) DO UPDATE SET account_id=EXCLUDED.account_id, account_login=EXCLUDED.account_login,"
            " account_type=EXCLUDED.account_type, status='connected', updated_at=now()",
            (body.installation_id, owner.get("id", 0), owner.get("login", body.owner), owner.get("type", "User")),
        )
        row = conn.execute(
            "INSERT INTO project_github_integrations (project_id, installation_id, repository_id, owner, repository_name, default_branch, status)"
            " VALUES (%s, %s, %s, %s, %s, %s, 'connected')"
            " ON CONFLICT (project_id) DO UPDATE SET installation_id=EXCLUDED.installation_id, repository_id=EXCLUDED.repository_id,"
            " owner=EXCLUDED.owner, repository_name=EXCLUDED.repository_name, default_branch=EXCLUDED.default_branch, status='connected', updated_at=now()"
            " RETURNING *",
            (project_id, body.installation_id, body.repository_id, body.owner, body.repository_name, default_branch),
        ).fetchone()
    return _out(dict(row))


@router.delete("/projects/{project_id}")
def disconnect_project_repository(project_id: UUID, x_factory_admin_token: str | None = Header(default=None)):
    _admin_token(x_factory_admin_token)
    with session() as conn:
        row = conn.execute(
            "UPDATE project_github_integrations SET status='disconnected', updated_at=now() WHERE project_id=%s AND status='connected' RETURNING project_id, status, updated_at",
            (project_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="GitHub project mapping not found")
    return _out(dict(row))


@router.post("/projects/{project_id}/runs/{run_id}/publish")
def publish_factory_run(project_id: UUID, run_id: UUID, x_factory_admin_token: str | None = Header(default=None)):
    _admin_token(x_factory_admin_token)
    service = _service()
    blocked = _require_configuration(service)
    if blocked:
        return blocked
    with session() as conn:
        mapping = _require_mapping(conn, project_id)
        project = conn.execute("SELECT * FROM projects WHERE id=%s", (project_id,)).fetchone()
        run = conn.execute("SELECT * FROM factory_runs WHERE id=%s AND project_id=%s", (run_id, project_id)).fetchone()
        if run is None:
            raise HTTPException(status_code=404, detail="factory run not found for this project")
        if run["status"] not in PUBLISHABLE_RUN_STATES:
            return _fail(409, "GITHUB_RUN_NOT_PUBLISHABLE", f"only verified runs can be published; this run is {run['status']}")
        files = _generated_files(conn, project_id, run_id)
    if not files:
        return _fail(409, "GITHUB_NO_GENERATED_FILES", "this run has no generated files to publish")
    installation_id = str(mapping["installation_id"])
    branch = factory_branch(project_id, run_id)
    message = f"Factory run {str(run_id)[:8]}: generated files for {project['name']}"
    try:
        remote_url = service.config.clone_url(mapping["owner"], mapping["repository_name"])
        access_token = service.installation_token(installation_id)
    except GitHubError as error:
        return _github_failure(error)
    try:
        with GitPublisher(remote_url, access_token, mapping["default_branch"], branch) as publisher:
            result = publisher.publish(files, message)
    except GitFlowError as error:
        return _git_failure(error)
    if not result.commit:
        return {"status": "NO_CHANGES", "branch": result.branch, "base_branch": result.base_branch, "remote_url": result.remote_url, "files_changed": []}
    with session() as conn:
        conn.execute(
            "INSERT INTO git_commits (project_id, factory_run_id, commit_hash, branch, base_branch, message, remote_url, files_changed, pushed_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())",
            (project_id, run_id, result.commit, result.branch, result.base_branch, result.message, result.remote_url, Jsonb(result.files_changed)),
        )
        event = conn.execute(
            "INSERT INTO factory_events (factory_run_id, stage, event_type, message) VALUES (%s, %s, 'github_push', %s) RETURNING id, created_at",
            (run_id, run["status"], f"Pushed {len(result.files_changed)} files to {result.branch} on {mapping['owner']}/{mapping['repository_name']}."),
        ).fetchone()
    return {
        "status": "PUSHED",
        "branch": result.branch,
        "base_branch": result.base_branch,
        "commit": result.commit,
        "message": result.message,
        "files_changed": result.files_changed,
        "remote_url": result.remote_url,
        "seeded_base_branch": result.seeded_base_branch,
        "event_id": str(event["id"]),
        "event_at": event["created_at"].isoformat(),
    }


@router.post("/projects/{project_id}/runs/{run_id}/pull-request", status_code=201)
def open_pull_request(project_id: UUID, run_id: UUID, x_factory_admin_token: str | None = Header(default=None)):
    _admin_token(x_factory_admin_token)
    service = _service()
    blocked = _require_configuration(service)
    if blocked:
        return blocked
    with session() as conn:
        mapping = _require_mapping(conn, project_id)
        project = conn.execute("SELECT * FROM projects WHERE id=%s", (project_id,)).fetchone()
        run = conn.execute("SELECT * FROM factory_runs WHERE id=%s AND project_id=%s", (run_id, project_id)).fetchone()
        if run is None:
            raise HTTPException(status_code=404, detail="factory run not found for this project")
        push = conn.execute(
            "SELECT branch, base_branch, commit_hash, files_changed FROM git_commits WHERE project_id=%s AND factory_run_id=%s AND remote_url IS NOT NULL ORDER BY created_at DESC LIMIT 1",
            (project_id, run_id),
        ).fetchone()
        if push is None:
            return _fail(409, "GITHUB_NOT_PUBLISHED", "publish this run to GitHub before opening a pull request")
        existing = conn.execute(
            "SELECT number, url FROM github_pull_requests WHERE project_id=%s AND factory_run_id=%s ORDER BY created_at DESC LIMIT 1",
            (project_id, run_id),
        ).fetchone()
        if existing is not None:
            return _fail(409, "GITHUB_PULL_REQUEST_EXISTS", f"pull request #{existing['number']} already exists for this run: {existing['url']}")
        tasks = conn.execute("SELECT agent_role, task_type, status, output, error FROM factory_tasks WHERE factory_run_id=%s ORDER BY started_at, id", (run_id,)).fetchall()
        artifacts = conn.execute("SELECT artifact_type, path FROM factory_artifacts WHERE factory_run_id=%s ORDER BY path", (run_id,)).fetchall()
        approval = conn.execute("SELECT status FROM approvals WHERE factory_run_id=%s ORDER BY created_at DESC LIMIT 1", (run_id,)).fetchone()
    body = _pull_request_body(
        dict(project),
        dict(run),
        [dict(task) for task in tasks],
        [dict(artifact) for artifact in artifacts],
        {**dict(push), "files_changed": push["files_changed"] or []},
        approval["status"] if approval else "NOT RECORDED",
    )
    title = f"[Factory] {project['name']} - run {str(run_id)[:8]}"
    try:
        pull = service.create_pull_request(mapping["owner"], mapping["repository_name"], title, body, push["branch"], push["base_branch"], str(mapping["installation_id"]))
    except GitHubError as error:
        return _github_failure(error)
    with session() as conn:
        row = conn.execute(
            "INSERT INTO github_pull_requests (project_id, factory_run_id, number, url, title, source_branch, target_branch, head_sha, status)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (project_id, run_id, pull.get("number"), pull.get("html_url", ""), title, push["branch"], push["base_branch"], (pull.get("head") or {}).get("sha", ""), "merged" if pull.get("merged") else (pull.get("state") or "open")),
        ).fetchone()
        conn.execute(
            "INSERT INTO factory_events (factory_run_id, stage, event_type, message) VALUES (%s, %s, 'github_pull_request', %s)",
            (run_id, run["status"], f"Opened pull request #{pull.get('number')} from {push['branch']} into {push['base_branch']}."),
        )
    return _out(dict(row))


@router.get("/projects/{project_id}/runs/{run_id}/pull-request")
def refresh_pull_request(project_id: UUID, run_id: UUID, x_factory_admin_token: str | None = Header(default=None)):
    _admin_token(x_factory_admin_token)
    service = _service()
    blocked = _require_configuration(service)
    if blocked:
        return blocked
    with session() as conn:
        mapping = _require_mapping(conn, project_id)
        row = conn.execute(
            "SELECT * FROM github_pull_requests WHERE project_id=%s AND factory_run_id=%s ORDER BY created_at DESC LIMIT 1",
            (project_id, run_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="no pull request is recorded for this run")
    try:
        pull = service.pull_request(mapping["owner"], mapping["repository_name"], row["number"], str(mapping["installation_id"]))
    except GitHubError as error:
        return _github_failure(error)
    status = "merged" if pull.get("merged") else (pull.get("state") or row["status"])
    with session() as conn:
        updated = conn.execute(
            "UPDATE github_pull_requests SET status=%s, url=%s, updated_at=now() WHERE id=%s RETURNING *",
            (status, pull.get("html_url") or row["url"], row["id"]),
        ).fetchone()
    return {
        **_out(dict(updated)),
        "state": pull.get("state"),
        "merged": bool(pull.get("merged")),
        "mergeable": pull.get("mergeable"),
        "draft": bool(pull.get("draft")),
        "commits": pull.get("commits"),
        "changed_files": pull.get("changed_files"),
        "additions": pull.get("additions"),
        "deletions": pull.get("deletions"),
        "head_ref": (pull.get("head") or {}).get("ref"),
        "head_sha": (pull.get("head") or {}).get("sha"),
        "base_ref": (pull.get("base") or {}).get("ref"),
    }


@router.post("/webhook")
async def github_webhook(request: Request, x_github_event: str | None = Header(default=None), x_hub_signature_256: str | None = Header(default=None)):
    config = GitHubConfig.from_env()
    if not config.webhook_secret:
        return _fail(503, "GITHUB_WEBHOOK_NOT_CONFIGURED", "GITHUB_WEBHOOK_SECRET is not configured on this server")
    body = await request.body()
    if len(body) > MAX_WEBHOOK_BYTES:
        return _fail(413, "GITHUB_WEBHOOK_TOO_LARGE", "webhook payload exceeded the accepted size")
    if not verify_webhook_signature(config.webhook_secret, body, x_hub_signature_256):
        return _fail(401, "GITHUB_WEBHOOK_SIGNATURE_INVALID", "webhook signature verification failed")
    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        return _fail(400, "GITHUB_WEBHOOK_PAYLOAD_INVALID", "webhook payload is not valid JSON")
    if not isinstance(payload, dict):
        return _fail(400, "GITHUB_WEBHOOK_PAYLOAD_INVALID", "webhook payload must be a JSON object")

    event = (x_github_event or "").strip()
    if event == "ping":
        return {"status": "PONG", "event": "ping"}
    installation = payload.get("installation") or {}
    installation_id = installation.get("id")
    account = installation.get("account") or {}
    if event == "installation" and installation_id:
        action = payload.get("action")
        if action in {"created", "new", "unsuspend"}:
            status = "connected"
        elif action in {"deleted", "suspend"}:
            status = "disconnected"
        else:
            return {"status": "IGNORED", "event": event, "action": action}
        with session() as conn:
            conn.execute(
                "INSERT INTO github_installations (installation_id, account_id, account_login, account_type, status) VALUES (%s, %s, %s, %s, %s)"
                " ON CONFLICT (installation_id) DO UPDATE SET account_login=EXCLUDED.account_login, account_type=EXCLUDED.account_type, status=EXCLUDED.status, updated_at=now()",
                (installation_id, account.get("id", 0), account.get("login", ""), account.get("type", "User"), status),
            )
        return {"status": "RECORDED", "event": event, "action": action, "installation_id": installation_id, "installation_status": status}
    if event == "installation_repositories" and installation_id:
        with session() as conn:
            conn.execute("UPDATE github_installations SET status='connected', updated_at=now() WHERE installation_id=%s", (installation_id,))
        return {"status": "RECORDED", "event": event, "installation_id": installation_id, "repositories_added": len(payload.get("repositories_added", [])), "repositories_removed": len(payload.get("repositories_removed", []))}
    if event == "pull_request":
        repository = payload.get("repository") or {}
        pull = payload.get("pull_request") or {}
        status = "merged" if pull.get("merged") else (pull.get("state") or "open")
        with session() as conn:
            updated = conn.execute(
                "UPDATE github_pull_requests SET status=%s, updated_at=now() WHERE project_id IN (SELECT project_id FROM project_github_integrations WHERE owner=%s AND repository_name=%s) AND number=%s RETURNING id",
                (status, repository.get("owner", {}).get("login", ""), repository.get("name", ""), pull.get("number")),
            ).fetchone()
        return {"status": "RECORDED" if updated else "IGNORED", "event": event, "action": payload.get("action"), "pull_request_status": status}
    return {"status": "IGNORED", "event": event or "unknown"}


@router.get("/webhook")
def github_webhook_configuration(x_factory_admin_token: str | None = Header(default=None)):
    _admin_token(x_factory_admin_token)
    config = GitHubConfig.from_env()
    return {"webhook_configured": bool(config.webhook_secret), "webhook_path": "/api/github/webhook"}