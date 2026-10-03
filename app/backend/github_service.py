import hashlib
import hmac
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Iterable

import httpx
import jwt


GITHUB_API = "https://api.github.com"
GITHUB_WEB = "https://github.com"

MAX_REPOSITORY_PAGES = 10
REPOSITORY_PAGE_SIZE = 100

_NAME_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_UNSAFE_TEXT = re.compile(r"[^A-Za-z0-9 .:/'\"()\[\]#@,+*-]")

ERROR_CODES = {
    400: "GITHUB_BAD_REQUEST",
    401: "GITHUB_UNAUTHORIZED",
    403: "GITHUB_FORBIDDEN",
    404: "GITHUB_NOT_FOUND",
    409: "GITHUB_CONFLICT",
    422: "GITHUB_UNPROCESSABLE",
    429: "GITHUB_RATE_LIMITED",
    500: "GITHUB_SERVER_ERROR",
    502: "GITHUB_BAD_GATEWAY",
    503: "GITHUB_UNAVAILABLE",
    504: "GITHUB_TIMEOUT",
}

CLIENT_STATUS = {
    400: 502,
    401: 502,
    403: 502,
    404: 404,
    409: 409,
    422: 422,
    429: 429,
    500: 502,
    502: 502,
    503: 503,
    504: 504,
}


def safe_text(value: Any, limit: int = 240) -> str:
    """Reduce a GitHub message to a single safe line for API responses."""
    text = _UNSAFE_TEXT.sub(" ", str(value or "")).strip()
    text = " ".join(text.split())
    return text[:limit] if text else ""


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    """Replace any known credential value in text with a placeholder."""
    cleaned = text
    for secret in secrets:
        if secret and len(secret) >= 8 and secret in cleaned:
            cleaned = cleaned.replace(secret, "[redacted]")
    return cleaned


def valid_name(value: str) -> bool:
    return bool(_NAME_SEGMENT.match(value or ""))


@dataclass(frozen=True)
class GitHubConfig:
    app_id: str
    app_name: str
    client_id: str
    client_secret: str
    private_key: str
    webhook_secret: str
    redirect_uri: str
    installation_id: str
    api_base_url: str = GITHUB_API
    web_base_url: str = GITHUB_WEB
    app_slug: str = ""
    timeout: float = 20.0

    @classmethod
    def from_env(cls):
        app_name = os.environ.get("GITHUB_APP_NAME", "")
        return cls(
            app_id=os.environ.get("GITHUB_APP_ID", ""),
            app_name=app_name,
            client_id=os.environ.get("GITHUB_CLIENT_ID", ""),
            client_secret=os.environ.get("GITHUB_CLIENT_SECRET", ""),
            private_key=os.environ.get("GITHUB_PRIVATE_KEY", ""),
            webhook_secret=os.environ.get("GITHUB_WEBHOOK_SECRET", ""),
            redirect_uri=os.environ.get("GITHUB_REDIRECT_URI", ""),
            installation_id=os.environ.get("GITHUB_INSTALLATION_ID", ""),
            api_base_url=(os.environ.get("GITHUB_API_BASE_URL") or GITHUB_API).rstrip("/"),
            web_base_url=(os.environ.get("GITHUB_WEB_BASE_URL") or GITHUB_WEB).rstrip("/"),
            app_slug=os.environ.get("GITHUB_APP_SLUG", ""),
            timeout=float(os.environ.get("GITHUB_TIMEOUT_SECONDS") or 20),
        )

    @property
    def configured(self):
        return all((self.app_id, self.app_name, self.client_id, self.client_secret, self.private_key, self.redirect_uri))

    @property
    def installation_configured(self):
        return self.configured and bool(self.installation_id)

    @property
    def slug(self):
        explicit = (self.app_slug or "").strip()
        if explicit:
            return explicit
        return re.sub(r"[^a-z0-9-]+", "-", (self.app_name or "").strip().lower()).strip("-")

    @property
    def install_url(self):
        return f"{self.web_base_url}/apps/{self.slug}/installations/new"

    def clone_url(self, owner: str, repository: str):
        if not (valid_name(owner) and valid_name(repository)):
            raise GitHubError(400, "owner and repository must be GitHub names", "GITHUB_BAD_REQUEST")
        return f"{self.web_base_url}/{owner}/{repository}.git"


class GitHubError(RuntimeError):
    def __init__(self, status: int, message: str, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code or ERROR_CODES.get(status, "GITHUB_ERROR")
        self.http_status = CLIENT_STATUS.get(status, 502)

    def payload(self) -> dict:
        return {"error": self.code, "message": safe_text(self)}


class GitHubService:
    def __init__(self, config: GitHubConfig | None = None, client: httpx.Client | None = None):
        self.config = config or GitHubConfig.from_env()
        self.client = client or httpx.Client(
            base_url=self.config.api_base_url,
            timeout=self.config.timeout,
            headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
        )
        self._tokens: dict[str, tuple[str, float]] = {}

    def _app_jwt(self):
        if not self.config.configured:
            raise GitHubError(503, "GitHub App is not configured")
        key = self.config.private_key.replace("\\n", "\n")
        now = int(time.time())
        return jwt.encode({"iat": now - 60, "exp": now + 540, "iss": self.config.app_id}, key, algorithm="RS256")

    def installation_token(self, installation_id: str | None = None):
        installation_id = str(installation_id or self.config.installation_id or "")
        if not installation_id.isdigit():
            raise GitHubError(503, "GitHub App installation is not configured")
        cached = self._tokens.get(installation_id)
        if cached and cached[1] > time.time() + 60:
            return cached[0]
        response = self._send(
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {self._app_jwt()}"},
        )
        payload = self._json(response, "GitHub installation token request failed")
        token = payload.get("token")
        if not token:
            raise GitHubError(502, "GitHub returned an installation token without a token value")
        expires_at = payload.get("expires_at")
        self._tokens[installation_id] = (token, _expiry_seconds(expires_at))
        return token

    def installation(self, installation_id: str | None = None):
        installation_id = str(installation_id or self.config.installation_id or "")
        response = self._send("GET", f"/app/installations/{installation_id}", headers={"Authorization": f"Bearer {self._app_jwt()}"})
        return self._json(response, "GitHub installation lookup failed")

    def request(self, method: str, path: str, installation_id: str | None = None, **kwargs: Any):
        token = self.installation_token(installation_id)
        headers = kwargs.pop("headers", {})
        response = self._send(method, path, headers={**headers, "Authorization": f"Bearer {token}"}, **kwargs)
        return self._json(response, "GitHub API request failed")

    def _send(self, method: str, path: str, **kwargs: Any):
        try:
            return self.client.request(method, path, **kwargs)
        except httpx.TimeoutException:
            raise GitHubError(504, "GitHub API request timed out")
        except httpx.RequestError:
            raise GitHubError(502, "GitHub API could not be reached")

    def _secrets(self) -> list[str]:
        """Credential values that must never appear in a message returned to a caller."""
        values = [self.config.client_secret, self.config.webhook_secret, self.config.private_key]
        values.extend(token for token, _ in self._tokens.values())
        return [value for value in values if value]

    def _json(self, response: httpx.Response, fallback: str):
        if response.status_code >= 400:
            raise GitHubError(response.status_code, _github_message(response, fallback, self._secrets()))
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            raise GitHubError(502, "GitHub returned a response that could not be decoded")

    def repositories(self, installation_id: str | None = None):
        repositories: list[dict] = []
        path: str | None = "/installation/repositories?per_page=100"
        for _ in range(MAX_REPOSITORY_PAGES):
            if path is None:
                break
            response = self._send("GET", path, headers={"Authorization": f"Bearer {self.installation_token(installation_id)}"})
            payload = self._json(response, "GitHub repository listing failed")
            repositories.extend(payload.get("repositories", []))
            path = _next_link(response.headers.get("link", ""))
        return repositories

    def repository(self, owner: str, name: str, installation_id: str | None = None):
        if not (valid_name(owner) and valid_name(name)):
            raise GitHubError(400, "owner and repository must be GitHub names", "GITHUB_BAD_REQUEST")
        return self.request("GET", f"/repos/{owner}/{name}", installation_id)

    def create_repository(self, name: str, private: bool, description: str, account_login: str | None = None, installation_id: str | None = None):
        """Create a repository through an organization installation token.

        GitHub only exposes repository creation for organization installations to
        installation access tokens. Personal-account installations are rejected
        honestly instead of pretending the call can succeed.
        """
        if not valid_name(name):
            raise GitHubError(422, "repository name is not valid", "GITHUB_UNPROCESSABLE")
        if not account_login or not valid_name(account_login):
            raise GitHubError(422, "an organization login is required to create a repository", "GITHUB_UNPROCESSABLE")
        installation = self.installation(installation_id)
        if str(installation.get("target_type") or installation.get("account", {}).get("type") or "").lower() != "organization":
            raise GitHubError(
                422,
                "GitHub App installation access tokens can only create repositories in an organization; repository selection still works",
                "GITHUB_UNPROCESSABLE",
            )
        return self.request(
            "POST",
            f"/orgs/{account_login}/repos",
            installation.get("id") or installation_id,
            json={"name": name, "private": private, "description": description or "", "auto_init": False},
        )

    def create_pull_request(self, owner: str, repository: str, title: str, body: str, source_branch: str, target_branch: str, installation_id: str | None = None):
        if not (valid_name(owner) and valid_name(repository)):
            raise GitHubError(400, "owner and repository must be GitHub names", "GITHUB_BAD_REQUEST")
        for branch in (source_branch, target_branch):
            if not _valid_ref(branch):
                raise GitHubError(422, "branch names are not valid git references", "GITHUB_UNPROCESSABLE")
        return self.request(
            "POST",
            f"/repos/{owner}/{repository}/pulls",
            installation_id,
            json={"title": title[:240], "body": body, "head": source_branch, "base": target_branch, "maintainer_can_modify": True},
        )

    def pull_request(self, owner: str, repository: str, number: int, installation_id: str | None = None):
        if not (valid_name(owner) and valid_name(repository)):
            raise GitHubError(400, "owner and repository must be GitHub names", "GITHUB_BAD_REQUEST")
        return self.request("GET", f"/repos/{owner}/{repository}/pulls/{int(number)}", installation_id)

    def branch_exists(self, owner: str, repository: str, branch: str, installation_id: str | None = None):
        if not _valid_ref(branch):
            raise GitHubError(422, "branch names are not valid git references", "GITHUB_UNPROCESSABLE")
        try:
            self.request("GET", f"/repos/{owner}/{repository}/git/ref/heads/{branch}", installation_id)
            return True
        except GitHubError as error:
            if error.status == 404:
                return False
            raise


def verify_webhook_signature(secret: str, body: bytes, signature: str | None) -> bool:
    if not secret or not signature:
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


def _valid_ref(branch: str) -> bool:
    if not branch or len(branch) > 200 or branch.startswith("/") or branch.endswith("/"):
        return False
    return all(re.fullmatch(r"[A-Za-z0-9._/-]+", segment) and ".." not in segment for segment in branch.split("/"))


def _expiry_seconds(expires_at: str | None) -> float:
    if expires_at:
        from datetime import datetime

        try:
            return datetime.fromisoformat(expires_at.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return time.time() + 3000


def _github_message(response: httpx.Response, fallback: str, secrets: Iterable[str] = ()) -> str:
    message = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            message = safe_text(redact(str(body.get("message") or ""), secrets))
    except ValueError:
        message = ""
    if response.status_code == 429:
        retry = safe_text(response.headers.get("retry-after"), 20)
        return f"{message or 'GitHub rate limit reached'}{f'; retry after {retry}s' if retry.isdigit() else ''}"
    if response.status_code == 404:
        return message or "GitHub reported that the resource no longer exists"
    return message or fallback


def _next_link(link_header: str) -> str | None:
    for part in link_header.split(","):
        segments = part.split(";")
        if len(segments) < 2:
            continue
        target = segments[0].strip().strip("<>")
        if any(segment.strip() == 'rel="next"' for segment in segments[1:]):
            return target
    return None