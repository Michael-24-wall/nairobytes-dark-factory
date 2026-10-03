"""Opt-in live GitHub verification.

These tests never run by accident. They require an explicit opt-in flag plus real
GitHub App credentials in the environment, because they talk to github.com and can
write a branch and a pull request to a real repository.

Read-only checks:
    NAIROBYTES_LIVE_GITHUB=1

Write check (pushes a branch and opens a pull request on a real repository):
    NAIROBYTES_LIVE_GITHUB=1
    NAIROBYTES_LIVE_GITHUB_WRITE=1
    NAIROBYTES_LIVE_GITHUB_REPOSITORY=owner/name

Without the flags every test reports NOT CONFIGURED instead of guessing a result.
"""

import os
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from app.backend.git_flow import GitPublisher, factory_branch
from app.backend.github_service import GitHubConfig, GitHubService

REQUIRED = (
    "GITHUB_APP_ID",
    "GITHUB_APP_NAME",
    "GITHUB_CLIENT_ID",
    "GITHUB_CLIENT_SECRET",
    "GITHUB_PRIVATE_KEY",
    "GITHUB_REDIRECT_URI",
)

live_enabled = pytest.mark.skipif(
    os.environ.get("NAIROBYTES_LIVE_GITHUB") != "1",
    reason="live GitHub testing is not enabled (set NAIROBYTES_LIVE_GITHUB=1)",
)
write_enabled = pytest.mark.skipif(
    os.environ.get("NAIROBYTES_LIVE_GITHUB") != "1" or os.environ.get("NAIROBYTES_LIVE_GITHUB_WRITE") != "1",
    reason="live GitHub write testing is not enabled (set NAIROBYTES_LIVE_GITHUB=1 and NAIROBYTES_LIVE_GITHUB_WRITE=1)",
)


def missing_configuration() -> list[str]:
    return [name for name in REQUIRED if not os.environ.get(name)]


@pytest.fixture(scope="module")
def live_config() -> GitHubConfig:
    missing = missing_configuration()
    if missing:
        pytest.skip(f"live GitHub credentials are not configured: missing {', '.join(missing)}")
    config = GitHubConfig.from_env()
    if not config.installation_id:
        pytest.skip("GITHUB_INSTALLATION_ID is not set, so no live installation can be queried")
    return config


@pytest.fixture(scope="module")
def live_service(live_config: GitHubConfig) -> GitHubService:
    return GitHubService(live_config)


@pytest.fixture(scope="module")
def live_target() -> tuple[str, str]:
    value = os.environ.get("NAIROBYTES_LIVE_GITHUB_REPOSITORY", "")
    if "/" not in value:
        pytest.skip("NAIROBYTES_LIVE_GITHUB_REPOSITORY is not set to owner/name")
    owner, _, name = value.partition("/")
    return owner, name


@live_enabled
def test_live_installation_is_readable(live_service: GitHubService, live_config: GitHubConfig):
    installation = live_service.installation(live_config.installation_id)
    account = installation.get("account") or {}
    assert installation.get("id") == int(live_config.installation_id)
    assert account.get("login"), "GitHub returned an installation without an account login"
    assert installation.get("permissions"), "GitHub returned an installation without permissions"


@live_enabled
def test_live_installation_token_is_usable(live_service: GitHubService, live_config: GitHubConfig):
    token = live_service.installation_token(live_config.installation_id)
    assert token.startswith(("ghs_", "github_pat_")), "unexpected installation token format"


@live_enabled
def test_live_repositories_are_listed(live_service: GitHubService, live_config: GitHubConfig):
    repositories = live_service.repositories(live_config.installation_id)
    assert isinstance(repositories, list)
    for repository in repositories:
        assert repository.get("full_name") and repository.get("id"), "repository entry is missing identity fields"


def remote_heads(publisher: GitPublisher) -> dict[str, str]:
    """Read the real remote refs through an authenticated ls-remote probe."""
    with tempfile.TemporaryDirectory(prefix="nairobytes-live-probe-") as probe:
        subprocess.run(["git", "init", "--quiet", "-b", "probe", probe], check=True, capture_output=True)
        subprocess.run(["git", "-C", probe, "remote", "add", "origin", publisher.remote_url], check=True, capture_output=True)
        return publisher.remote_heads(Path(probe))


@write_enabled
def test_live_push_and_pull_request(live_service: GitHubService, live_config: GitHubConfig, live_target: tuple[str, str]):
    owner, name = live_target
    repository = live_service.repository(owner, name, live_config.installation_id)
    base_branch = repository.get("default_branch") or "main"
    token = live_service.installation_token(live_config.installation_id)
    branch = factory_branch(uuid4(), uuid4())
    marker = f"nairobytes-live-{uuid4()}"
    files = {f".nairobytes/{marker}.md": f"# Live verification\n\nmarker: {marker}\n".encode("utf-8")}

    with GitPublisher(live_service.config.clone_url(owner, name), token, base_branch, branch) as publisher:
        heads_before = remote_heads(publisher)
        result = publisher.publish(files, f"Live verification {marker}")
        heads_after = remote_heads(publisher)

    assert result.commit, "the live push produced no commit"
    assert result.files_changed == list(files), f"unexpected changed files: {result.files_changed}"
    assert heads_after[branch] == result.commit, "the remote branch does not match the pushed commit"
    assert heads_after.get(base_branch) == heads_before.get(base_branch), "the default branch was modified"

    pull = live_service.create_pull_request(
        owner,
        name,
        f"[Live verification] {marker}",
        f"Automated live verification of the Nairobytes Dark Factory git flow.\n\nmarker: {marker}",
        branch,
        base_branch,
        live_config.installation_id,
    )
    assert pull.get("number"), "GitHub did not return a pull request number"
    assert pull.get("html_url", "").startswith("https://github.com/"), "pull request URL is not a github.com URL"

    refreshed = live_service.pull_request(owner, name, pull["number"], live_config.installation_id)
    assert refreshed.get("number") == pull["number"]
    assert refreshed.get("head", {}).get("ref") == branch
    assert refreshed.get("base", {}).get("ref") == base_branch
    print(f"live branch {branch} at {result.commit}; pull request {pull['html_url']}")
