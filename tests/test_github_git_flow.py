import subprocess
from pathlib import Path

import pytest

from app.backend.git_flow import GitFlowError, GitPublisher, factory_branch


def bare_remote(root: Path, name: str) -> Path:
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--bare", "--quiet", "-b", "main", str(target)], check=True, capture_output=True)
    return target


def git_show(remote: Path, ref: str, path: str) -> str:
    result = subprocess.run(["git", "--git-dir", str(remote), "show", f"{ref}:{path}"], capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else ""


def test_factory_branch_name_follows_the_documented_convention():
    assert factory_branch("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222") == (
        "factory/project-11111111-1111-1111-1111-111111111111/run-22222222-2222-2222-2222-222222222222"
    )


def test_publish_pushes_real_files_to_a_real_branch_on_a_real_remote(tmp_path):
    remote = bare_remote(tmp_path / "remotes", "acme-widget.git")
    branch = factory_branch("project-1", "run-2")

    with GitPublisher(remote.as_uri(), "", "main", branch) as publisher:
        result = publisher.publish(
            {"index.html": b"<h1>factory</h1>", "styles.css": b"body{}", "public/assets/logo.svg": b"<svg/>"},
            "Factory run 2: generated project files",
        )

    assert result.commit
    assert result.remote_commit == result.commit
    assert result.branch == branch
    assert result.files_changed == ["index.html", "public/assets/logo.svg", "styles.css"]

    heads = subprocess.run(["git", "ls-remote", "--heads", str(remote)], capture_output=True, text=True).stdout
    assert f"refs/heads/{branch}" in heads
    assert git_show(remote, branch, "index.html") == "<h1>factory</h1>"
    assert git_show(remote, branch, "public/assets/logo.svg") == "<svg/>"


def test_publish_never_writes_factory_files_to_the_default_branch(tmp_path):
    remote = bare_remote(tmp_path / "remotes", "acme-widget.git")
    branch = factory_branch("project-1", "run-3")

    with GitPublisher(remote.as_uri(), "", "main", branch) as publisher:
        result = publisher.publish({"index.html": b"<h1>factory</h1>"}, "Factory run 3")

    assert result.seeded_base_branch is True
    assert "index.html" in result.files_changed
    assert git_show(remote, "main", "index.html") == ""
    assert git_show(remote, branch, "index.html") == "<h1>factory</h1>"


def test_publish_rebases_onto_an_existing_default_branch(tmp_path):
    remote = bare_remote(tmp_path / "remotes", "acme-widget.git")
    seed = tmp_path / "seed"
    seed.mkdir()
    subprocess.run(["git", "init", "--quiet", "-b", "main", "."], cwd=seed, check=True, capture_output=True)
    (seed / "LICENSE").write_text("existing project licence\n", encoding="utf-8")
    subprocess.run(["git", "add", "--all"], cwd=seed, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "--quiet", "-m", "existing"], cwd=seed, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", remote.as_uri()], cwd=seed, check=True, capture_output=True)
    subprocess.run(["git", "push", "--quiet", "origin", "main"], cwd=seed, check=True, capture_output=True)

    branch = factory_branch("project-1", "run-4")
    with GitPublisher(remote.as_uri(), "", "main", branch) as publisher:
        result = publisher.publish({"index.html": b"<h1>factory</h1>"}, "Factory run 4")

    assert result.seeded_base_branch is False
    assert result.files_changed == ["index.html"]
    assert git_show(remote, branch, "LICENSE") == "existing project licence\n"
    assert git_show(remote, branch, "index.html") == "<h1>factory</h1>"
    assert git_show(remote, "main", "index.html") == ""


def test_republishing_identical_files_reports_no_new_commit(tmp_path):
    remote = bare_remote(tmp_path / "remotes", "acme-widget.git")
    branch = factory_branch("project-1", "run-5")
    files = {"index.html": b"<h1>factory</h1>"}

    with GitPublisher(remote.as_uri(), "", "main", branch) as first:
        first_result = first.publish(files, "Factory run 5")
    with GitPublisher(remote.as_uri(), "", "main", branch) as second:
        second_result = second.publish(files, "Factory run 5 again")

    assert first_result.commit
    assert second_result.commit == ""
    assert second_result.files_changed == []


def test_publish_refuses_paths_outside_the_publish_directory(tmp_path):
    remote = bare_remote(tmp_path / "remotes", "acme-widget.git")
    with GitPublisher(remote.as_uri(), "", "main", "factory/run") as publisher:
        with pytest.raises(GitFlowError) as failure:
            publisher.publish({"../escape.txt": b"nope"}, "escape attempt")
    assert failure.value.code == "GIT_UNSAFE_PATH"


def test_push_failure_is_reported_without_exposing_the_token(tmp_path):
    token = "ghs_thisisatesttokenvalue000000000000"
    with GitPublisher("https://127.0.0.1:1/acme/widget.git", token, "main", "factory/run") as publisher:
        with pytest.raises(GitFlowError) as failure:
            publisher.publish({"index.html": b"<h1>factory</h1>"}, "unreachable remote")
    assert failure.value.code == "GIT_FAILED"
    assert token not in str(failure.value)


def test_publish_requires_a_remote_url():
    with pytest.raises(GitFlowError) as failure:
        GitPublisher("", "token", "main", "factory/run")
    assert failure.value.code == "GIT_REMOTE_MISSING"