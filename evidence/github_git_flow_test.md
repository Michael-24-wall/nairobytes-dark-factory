# Git Flow Evidence

Date: 2026-10-03

## What was verified locally

Command:

```text
.venv\Scripts\python.exe -m pytest tests/test_github_git_flow.py -q
```

Observed:

```text
8 passed in 19.40s
```

These tests run real `git` (`git version 2.55.0.windows.2`) against a real bare repository created in a temporary directory. They are not mocked.

## Branch and push behaviour

- The factory branch is `factory/project-{project_id}/run-{run_id}`, built by `factory_branch()` in `app/backend/git_flow.py`.
- `publish()` initializes a temporary repository, adds the real clone URL as `origin`, reads the remote heads with `git ls-remote --heads origin`, and then:
  - if the factory branch already exists remotely, it fetches that branch and resets the local branch to `FETCH_HEAD`;
  - otherwise, if the default branch exists remotely, it branches from that commit;
  - otherwise the remote is empty, so it writes one `README.md`, commits it on the default branch, pushes it, and continues.
- Only the generated files are staged and committed. After the push the remote head is read again and compared with the local commit SHA; a mismatch raises `GIT_PUSH_UNVERIFIED` instead of reporting success.
- If the generated content is identical to what is already on the branch, nothing is committed and the API reports `NO_CHANGES`.
- The default branch is never modified once it exists. The only write to it is the initial README commit for an empty repository, and the response reports `seeded_base_branch` so this is visible.

## Credential handling during push

- Authentication uses a temporary `GIT_ASKPASS` script created in a `tempfile.mkdtemp` directory and removed when the publisher closes. The token is passed through an environment variable, never through a command line argument or a remote URL.
- `GIT_TERMINAL_PROMPT=0`, `GIT_CONFIG_NOSYSTEM=1`, and an empty `credential.helper` prevent interactive prompts and credential-helper leakage.
- All captured stdout and stderr is scrubbed: the token is replaced with `***` before any message is raised, returned, or recorded.

## Path safety

`_safe_target()` resolves every generated path inside the temporary publish directory and raises `GIT_UNSAFE_PATH` for absolute paths, `..` segments, or anything that resolves outside the directory.

## Backend integration

`POST /api/github/projects/{project_id}/runs/{run_id}/publish`:

1. requires an authenticated admin caller;
2. requires a connected project mapping;
3. requires the run to belong to that project and to be in a publishable state (`awaiting_approval` or `approved`), otherwise `409 GITHUB_RUN_NOT_PUBLISHABLE`;
4. reads the real artifact bytes from the project workspace, ignoring any artifact path that does not resolve to a real file inside it, and returns `409 GITHUB_NO_GENERATED_FILES` when nothing remains;
5. resolves the clone URL from the mapped owner and repository and mints an installation token;
6. pushes, then records the commit hash, branch, base branch, message, remote URL, changed file list, and `pushed_at` in `git_commits`, and writes a `github_push` factory event into the run timeline.

## Live status

`NOT TESTED`. The pushes in these tests went to local bare repositories over `file://`, not to github.com. No GitHub App credentials or installation exist in this environment, so no live branch was created and no live push occurred. The opt-in live test `tests/test_github_live.py::test_live_push_and_pull_request` exists for a configured environment and skips without `NAIROBYTES_LIVE_GITHUB=1` and `NAIROBYTES_LIVE_GITHUB_WRITE=1`.