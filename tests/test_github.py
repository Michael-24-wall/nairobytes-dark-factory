import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from app.backend.github_service import GitHubConfig, GitHubError, GitHubService, verify_webhook_signature


def config():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    return GitHubConfig("123", "factory-app", "client", "secret", key, "webhook", "http://localhost/callback", "456")


def test_missing_github_app_configuration_is_explicit(monkeypatch):
    for name in ("GITHUB_APP_ID", "GITHUB_APP_NAME", "GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET", "GITHUB_PRIVATE_KEY", "GITHUB_INSTALLATION_ID"):
        monkeypatch.delenv(name, raising=False)
    assert GitHubConfig.from_env().configured is False


def test_installation_token_and_repository_list_use_github_api():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, request.headers.get("authorization", "")))
        if request.url.path == "/app/installations/456/access_tokens":
            return httpx.Response(201, json={"token": "short-lived-token"})
        if request.url.path == "/installation/repositories":
            return httpx.Response(200, json={"repositories": [{"id": 99, "full_name": "owner/repo", "default_branch": "main"}]})
        return httpx.Response(404)

    service = GitHubService(config(), httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.github.com"))
    repositories = service.repositories()
    assert repositories[0]["id"] == 99
    assert calls[0][1] == "/app/installations/456/access_tokens"
    assert calls[1][2] == "Bearer short-lived-token"


def test_github_service_rejects_unconfigured_calls():
    service = GitHubService(GitHubConfig("", "", "", "", "", "", "", ""), httpx.Client(base_url="https://api.github.com"))
    with pytest.raises(GitHubError, match="not configured"):
        service.repositories()


def service_with(handler, settings=None):
    return GitHubService(settings or config(), httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.github.com"))


def test_app_jwt_is_signed_by_the_configured_private_key():
    settings = config()
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    settings = GitHubConfig("987654", settings.app_name, settings.client_id, settings.client_secret, pem.replace("\n", "\\n"), settings.webhook_secret, settings.redirect_uri, settings.installation_id)
    claims = jwt.decode(service_with(lambda request: httpx.Response(404), settings)._app_jwt(), private.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo), algorithms=["RS256"])
    assert claims["iss"] == "987654"
    assert claims["exp"] - claims["iat"] == 600


def test_installation_token_is_requested_once_per_installation():
    seen = []

    def handler(request):
        if request.url.path.endswith("/access_tokens"):
            seen.append(request.url.path)
            return httpx.Response(201, json={"token": f"token-for-{request.url.path}", "expires_at": "2999-01-01T00:00:00Z"})
        return httpx.Response(200, json={"repositories": []})

    service = service_with(handler)
    service.repositories()
    service.repositories()
    service.repositories("789")
    assert seen == ["/app/installations/456/access_tokens", "/app/installations/789/access_tokens"]


def test_installation_token_rejects_a_non_numeric_installation_id():
    settings = GitHubConfig("123", "factory-app", "client", "secret", "key", "webhook", "http://localhost/callback", "not-a-number")
    with pytest.raises(GitHubError, match="not configured"):
        service_with(lambda request: httpx.Response(200, json={}), settings).installation_token()


def test_repositories_follow_pagination_links():
    def handler(request):
        if request.url.path.endswith("/access_tokens"):
            return httpx.Response(201, json={"token": "t", "expires_at": "2999-01-01T00:00:00Z"})
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json={"repositories": [{"id": 2}]})
        return httpx.Response(200, json={"repositories": [{"id": 1}]}, headers={"Link": '<https://api.github.com/installation/repositories?per_page=100&page=2>; rel="next"'})

    repositories = service_with(handler).repositories()
    assert [repo["id"] for repo in repositories] == [1, 2]


@pytest.mark.parametrize(
    "github_status,expected_code,expected_http",
    [
        (401, "GITHUB_UNAUTHORIZED", 502),
        (403, "GITHUB_FORBIDDEN", 502),
        (404, "GITHUB_NOT_FOUND", 404),
        (409, "GITHUB_CONFLICT", 409),
        (422, "GITHUB_UNPROCESSABLE", 422),
        (429, "GITHUB_RATE_LIMITED", 429),
        (500, "GITHUB_SERVER_ERROR", 502),
    ],
)
def test_github_http_failures_are_coded_and_sanitised(github_status, expected_code, expected_http):
    def handler(request):
        if request.url.path.endswith("/access_tokens"):
            return httpx.Response(201, json={"token": "t", "expires_at": "2999-01-01T00:00:00Z"})
        return httpx.Response(github_status, json={"message": "token ghs_should_never_leak\nstack trace ../../etc/passwd", "documentation_url": "https://docs.github.com/rest"})

    with pytest.raises(GitHubError) as failure:
        service_with(handler).repositories()
    assert failure.value.code == expected_code
    assert failure.value.http_status == expected_http
    assert "ghs_should_never_leak" not in str(failure.value)
    assert "\n" not in str(failure.value)
    assert "docs.github.com" not in str(failure.value)


def test_known_credentials_are_redacted_from_github_error_messages():
    token = "ghs_16C7e42F292c6912E7710c838347Ae178B4a"

    def handler(request):
        if request.url.path.endswith("/access_tokens"):
            return httpx.Response(201, json={"token": token, "expires_at": "2999-01-01T00:00:00Z"})
        return httpx.Response(422, json={"message": f"bad token {token} with client secret super-secret-value"})

    settings = GitHubConfig("123", "factory-app", "client", "super-secret-value", config().private_key, "webhook", "http://localhost/callback", "456")
    with pytest.raises(GitHubError) as failure:
        service_with(handler, settings).repositories()
    assert token not in str(failure.value)
    assert "super-secret-value" not in str(failure.value)
    assert str(failure.value).count("[redacted]") == 2


def test_timeouts_are_reported_as_gateway_timeout():
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(GitHubError) as failure:
        service_with(handler).repositories()
    assert failure.value.code == "GITHUB_TIMEOUT"
    assert failure.value.http_status == 504


def test_connection_failures_are_reported_as_bad_gateway():
    def handler(request):
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(GitHubError) as failure:
        service_with(handler).repositories()
    assert failure.value.code == "GITHUB_BAD_GATEWAY"


def test_webhook_signature_verification_only_accepts_a_matching_hmac():
    import hashlib
    import hmac

    body = b'{"action":"created"}'
    signature = "sha256=" + hmac.new(b"hook-secret", body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature("hook-secret", body, signature) is True
    assert verify_webhook_signature("hook-secret", body, signature[:-1] + "0") is False
    assert verify_webhook_signature("hook-secret", b'{"action":"deleted"}', signature) is False
    assert verify_webhook_signature("hook-secret", body, None) is False
    assert verify_webhook_signature("", body, signature) is False


def test_configuration_exposes_only_public_install_and_clone_urls(monkeypatch):
    for name, value in (
        ("GITHUB_APP_ID", "1"),
        ("GITHUB_APP_NAME", "Nairobytes Factory"),
        ("GITHUB_CLIENT_ID", "c"),
        ("GITHUB_CLIENT_SECRET", "s"),
        ("GITHUB_PRIVATE_KEY", "-----BEGIN PRIVATE KEY-----"),
        ("GITHUB_REDIRECT_URI", "http://127.0.0.1:5173/settings/github"),
        ("GITHUB_INSTALLATION_ID", "42"),
    ):
        monkeypatch.setenv(name, value)
    settings = GitHubConfig.from_env()
    assert settings.configured is True
    assert settings.installation_configured is True
    assert settings.slug == "nairobytes-factory"
    assert settings.install_url == "https://github.com/apps/nairobytes-factory/installations/new"
    assert settings.clone_url("acme", "widget") == "https://github.com/acme/widget.git"


def test_configuration_requires_every_credential(monkeypatch):
    monkeypatch.setenv("GITHUB_APP_ID", "1")
    monkeypatch.setenv("GITHUB_APP_NAME", "app")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "c")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "s")
    monkeypatch.setenv("GITHUB_PRIVATE_KEY", "key")
    monkeypatch.delenv("GITHUB_REDIRECT_URI", raising=False)
    assert GitHubConfig.from_env().configured is False


def test_clone_url_rejects_path_traversal():
    with pytest.raises(GitHubError) as failure:
        config().clone_url("../../etc", "passwd")
    assert failure.value.code == "GITHUB_BAD_REQUEST"


def test_repository_lookup_rejects_unsafe_names():
    with pytest.raises(GitHubError):
        GitHubService(config(), httpx.Client(base_url="https://api.github.com")).repository("owner/../../etc", "repo")


def test_repository_creation_requires_an_organization_installation():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/access_tokens"):
            return httpx.Response(201, json={"token": "t", "expires_at": "2999-01-01T00:00:00Z"})
        if request.url.path == "/app/installations/456":
            return httpx.Response(200, json={"id": 456, "target_type": "User", "account": {"login": "mona", "type": "User"}})
        return httpx.Response(201, json={"id": 5, "name": "widget"})

    with pytest.raises(GitHubError) as failure:
        service_with(handler).create_repository("widget", True, "", None)
    assert failure.value.code == "GITHUB_UNPROCESSABLE"
    assert [path for _method, path in calls].count("/user/repos") == 0


def test_repository_creation_uses_the_organization_endpoint():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, request.headers.get("authorization")))
        if request.url.path.endswith("/access_tokens"):
            return httpx.Response(201, json={"token": "t", "expires_at": "2999-01-01T00:00:00Z"})
        if request.url.path == "/app/installations/456":
            return httpx.Response(200, json={"id": 456, "target_type": "Organization", "account": {"login": "acme", "type": "Organization"}})
        return httpx.Response(201, json={"id": 5, "name": "widget", "full_name": "acme/widget"})

    created = service_with(handler).create_repository("widget", True, "factory output", "acme")
    assert created["full_name"] == "acme/widget"
    assert ("POST", "/orgs/acme/repos", "Bearer t") in calls


def test_repository_creation_requires_an_organization_login():
    with pytest.raises(GitHubError) as failure:
        service_with(lambda request: httpx.Response(200, json={})).create_repository("widget", True, "", None)
    assert failure.value.code == "GITHUB_UNPROCESSABLE"


def test_pull_request_creation_uses_real_head_and_base():
    seen = {}

    def handler(request):
        if request.url.path.endswith("/access_tokens"):
            return httpx.Response(201, json={"token": "t", "expires_at": "2999-01-01T00:00:00Z"})
        seen["path"] = request.url.path
        seen["payload"] = request.read().decode()
        return httpx.Response(201, json={"number": 12, "html_url": "https://github.com/acme/widget/pull/12"})

    service = service_with(handler)
    service.create_pull_request("acme", "widget", "title", "body", "factory/project-1/run-2", "main")
    assert seen["path"] == "/repos/acme/widget/pulls"
    assert '"head":"factory/project-1/run-2"' in seen["payload"]
    assert '"base":"main"' in seen["payload"]


def test_pull_request_creation_rejects_unsafe_references():
    with pytest.raises(GitHubError) as failure:
        service_with(lambda request: httpx.Response(200, json={})).create_pull_request("acme", "widget", "t", "b", "main..evil", "main")
    assert failure.value.code == "GITHUB_UNPROCESSABLE"


def test_branch_presence_is_reported_without_raising_for_missing_branches():
    def handler(request):
        if request.url.path.endswith("/access_tokens"):
            return httpx.Response(201, json={"token": "t", "expires_at": "2999-01-01T00:00:00Z"})
        if request.url.path.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"ref": "refs/heads/main"})
        return httpx.Response(404, json={"message": "Not Found"})

    service = service_with(handler)
    assert service.branch_exists("acme", "widget", "main") is True
    assert service.branch_exists("acme", "widget", "factory/run-9") is False