import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

GIT_TIMEOUT_SECONDS = 180
GIT_AUTHOR_NAME = "Nairobytes Dark Factory"
GIT_AUTHOR_EMAIL = "factory@nairobytes.local"


class GitFlowError(RuntimeError):
    def __init__(self, code: str, message: str, step: str = ""):
        super().__init__(message)
        self.code = code
        self.step = step

    def payload(self) -> dict:
        return {"error": self.code, "message": str(self)}


@dataclass(frozen=True)
class PublishResult:
    branch: str
    base_branch: str
    commit: str
    message: str
    files_changed: list[str] = field(default_factory=list)
    remote_url: str = ""
    seeded_base_branch: bool = False
    remote_commit: str = ""


def factory_branch(project_id, run_id) -> str:
    return f"factory/project-{project_id}/run-{run_id}"


class GitPublisher:
    """Publish real generated files to a real git remote over a real push."""

    def __init__(self, remote_url: str, token: str, base_branch: str = "main", branch: str = "factory/run"):
        if not remote_url:
            raise GitFlowError("GIT_REMOTE_MISSING", "no remote repository URL was resolved for this project")
        self.remote_url = remote_url
        self.token = token or ""
        self.base_branch = base_branch or "main"
        self.branch = branch
        self._askpass_dir = None

    def _scrub(self, text: str) -> str:
        if not text:
            return ""
        if self.token:
            text = text.replace(self.token, "***")
        return text

    def _environment(self):
        env = {
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GCM_INTERACTIVE": "never",
            "NAIROBYTES_GITHUB_TOKEN": self.token,
        }
        if self.token:
            self._askpass_dir = self._askpass_dir or tempfile.mkdtemp(prefix="nairobytes-git-auth-")
            if os.name == "nt":
                script = Path(self._askpass_dir) / "askpass.cmd"
                script.write_text(
                    "@echo off\r\n"
                    "echo %1 | findstr /i \"username\" >nul\r\n"
                    "if not errorlevel 1 (echo x-access-token & exit /b 0)\r\n"
                    "echo %NAIROBYTES_GITHUB_TOKEN%\r\n",
                    encoding="utf-8",
                )
            else:
                script = Path(self._askpass_dir) / "askpass.sh"
                script.write_text(
                    "#!/bin/sh\ncase \"$1\" in\n  *[Uu]sername*) printf '%s\\n' x-access-token ;;\n"
                    "  *) printf '%s\\n' \"$NAIROBYTES_GITHUB_TOKEN\" ;;\nesac\n",
                    encoding="utf-8",
                )
                script.chmod(0o700)
            env["GIT_ASKPASS"] = str(script)
        return env

    def _git(self, arguments, cwd: Path):
        command = ["git", "-c", "credential.helper=", "-c", "advice.detachedHead=false", *arguments]
        try:
            result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS, env=self._environment())
        except subprocess.TimeoutExpired:
            raise GitFlowError("GIT_TIMEOUT", "git command timed out", " ".join(arguments[:2]))
        except FileNotFoundError:
            raise GitFlowError("GIT_MISSING", "git is not installed or not on PATH", " ".join(arguments[:2]))
        if result.returncode != 0:
            detail = self._scrub(result.stderr.strip() or result.stdout.strip())
            raise GitFlowError("GIT_FAILED", f"git {' '.join(arguments[:2])} failed: {detail}"[:900], " ".join(arguments[:2]))
        return self._scrub(result.stdout)

    def close(self):
        if self._askpass_dir:
            shutil.rmtree(self._askpass_dir, ignore_errors=True)
            self._askpass_dir = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def remote_heads(self, workdir: Path) -> dict[str, str]:
        output = self._git(["ls-remote", "--heads", "origin"], workdir)
        heads = {}
        for line in output.splitlines():
            sha, _, ref = line.partition("\t")
            if ref.startswith("refs/heads/"):
                heads[ref[len("refs/heads/"):]] = sha.strip()
        return heads

    def publish(self, files: dict[str, bytes], message: str) -> PublishResult:
        workdir = Path(tempfile.mkdtemp(prefix="nairobytes-publish-"))
        try:
            self._init_repository(workdir)
            self._git(["config", "user.name", GIT_AUTHOR_NAME], workdir)
            self._git(["config", "user.email", GIT_AUTHOR_EMAIL], workdir)
            self._git(["remote", "add", "origin", self.remote_url], workdir)
            heads = self.remote_heads(workdir)
            seeded = False
            if self.branch in heads:
                self._git(["fetch", "--quiet", "origin", self.branch], workdir)
                self._git(["checkout", "--quiet", "-B", self.branch, "FETCH_HEAD"], workdir)
            elif self.base_branch in heads:
                self._git(["fetch", "--quiet", "origin", self.base_branch], workdir)
                self._git(["checkout", "--quiet", "-b", self.branch, "FETCH_HEAD"], workdir)
            else:
                seeded = self._seed_base_branch(workdir)
                self._git(["checkout", "--quiet", "-b", self.branch], workdir)
            changed = self._stage(workdir, files)
            if not changed:
                return PublishResult(branch=self.branch, base_branch=self.base_branch, commit="", message=message, remote_url=self.remote_url, seeded_base_branch=seeded)
            self._git(["commit", "--quiet", "-m", message], workdir)
            commit = self._git(["rev-parse", "HEAD"], workdir).strip()
            self._git(["push", "--quiet", "origin", f"refs/heads/{self.branch}:refs/heads/{self.branch}"], workdir)
            pushed = self.remote_heads(workdir).get(self.branch, "")
            if pushed != commit:
                raise GitFlowError("GIT_PUSH_UNVERIFIED", "the pushed branch does not match the local commit", "push")
            return PublishResult(branch=self.branch, base_branch=self.base_branch, commit=commit, message=message, files_changed=changed, remote_url=self.remote_url, seeded_base_branch=seeded, remote_commit=pushed)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _init_repository(self, workdir: Path):
        try:
            self._git(["init", "--quiet", "-b", self.base_branch, "."], workdir)
        except GitFlowError:
            self._git(["init", "--quiet", "."], workdir)
            self._git(["symbolic-ref", "HEAD", f"refs/heads/{self.base_branch}"], workdir)

    def _seed_base_branch(self, workdir: Path) -> bool:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        (workdir / "README.md").write_text(
            f"# Initialised by Nairobytes Dark Factory\n\nThis repository was initialised by the Dark Factory because it was empty when the first factory run published to it. Generated project files are delivered through factory branches and pull requests.\n\nInitialised at {stamp}.\n",
            encoding="utf-8",
        )
        self._git(["checkout", "--quiet", "-B", self.base_branch], workdir)
        self._git(["add", "--all"], workdir)
        self._git(["commit", "--quiet", "-m", "Initialise empty repository from Nairobytes Dark Factory"], workdir)
        self._git(["push", "--quiet", "origin", f"refs/heads/{self.base_branch}:refs/heads/{self.base_branch}"], workdir)
        return True

    def _stage(self, workdir: Path, files: dict[str, bytes]) -> list[str]:
        for relative, content in files.items():
            target = _safe_target(workdir, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content if isinstance(content, bytes) else str(content).encode("utf-8"))
        self._git(["add", "--all"], workdir)
        status = self._git(["status", "--porcelain"], workdir)
        changed = []
        for line in status.splitlines():
            entry = line[3:].strip() if len(line) > 3 else ""
            if " -> " in entry:
                entry = entry.split(" -> ", 1)[1]
            if entry:
                changed.append(entry.strip('"'))
        return sorted(changed)


def _safe_target(workdir: Path, relative: str) -> Path:
    if not relative or relative.startswith("/") or ".." in Path(relative).parts:
        raise GitFlowError("GIT_UNSAFE_PATH", "a generated file path escaped the publish directory")
    target = (workdir / relative).resolve()
    if workdir.resolve() not in target.parents:
        raise GitFlowError("GIT_UNSAFE_PATH", "a generated file path escaped the publish directory")
    return target