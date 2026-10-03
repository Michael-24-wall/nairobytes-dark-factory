# Pull Request Evidence

Date: 2026-10-03

## What was verified locally

Commands:

```text
.venv\Scripts\python.exe -m pytest tests/test_github_api.py -q
.venv\Scripts\python.exe -m pytest tests/test_github.py -q
```

Observed:

```text
33 passed, 1 warning in 48.58s
28 passed in 10.33s
```

The pull request tests run through the HTTP API against a deterministic mocked GitHub API. They are not live GitHub activity.

## Creation

`POST /api/github/projects/{project_id}/runs/{run_id}/pull-request` calls `POST /repos/{owner}/{repo}/pulls` with the installation token.

- It requires a connected project mapping and a run that belongs to that project.
- It requires an earlier real push for that run. Without a recorded `git_commits` row the request returns `409 GITHUB_NOT_PUBLISHED`, so a pull request can never reference files that were not published.
- A second pull request for the same run returns `409 GITHUB_PULL_REQUEST_EXISTS` and names the existing number and URL.
- Head and base are the pushed factory branch and the mapped default branch. Both branch names are validated before the request is built.
- The title is `[Factory] {project name} - run {first 8 characters of the run id}`.

## Pull request body

The body is generated from the database record, not from a template with invented results:

- the run status, current stage, and run id;
- every recorded `factory_tasks` row with its agent role, task type, status, and output or error text;
- every recorded `factory_artifacts` path;
- the exact pushed file list from `git_commits.files_changed` and the commit SHA;
- the latest recorded approval status, or `NOT RECORDED` when none exists.

## Reading state back

`GET /api/github/projects/{project_id}/runs/{run_id}/pull-request` calls `GET /repos/{owner}/{repo}/pulls/{number}` and returns `state`, `merged`, `mergeable`, `draft`, `commits`, `changed_files`, `additions`, `deletions`, `head_ref`, `head_sha`, and `base_ref` together with the stored record. The stored status is updated in `github_pull_requests`.

- A run with no recorded pull request returns `404`.
- A pull request that no longer exists on GitHub returns `404 GITHUB_NOT_FOUND` rather than a stale success.
- A merged pull request is recorded as `merged`.

## Webhooks

A signed `pull_request` webhook with action `opened`, `edited`, `closed`, `reopened`, or `synchronize` updates the stored status for the matching repository and number, and appends a factory event. An unsigned or incorrectly signed payload returns `401`. With no `GITHUB_WEBHOOK_SECRET` configured the route returns `503` and accepts nothing.

## Persistence and UI

The number, URL, title, head SHA, source branch, target branch, and status are stored in `github_pull_requests`. `/projects/{id}/github` shows the recorded pull request, links to it on github.com, and offers **Refresh from GitHub** so the displayed state always comes from a fresh API read.

## Live status

`NOT CONFIGURED`. No GitHub App credentials, installation, or `.env` file exist in this environment, so no pull request was opened on github.com and no live pull request state was read. A pull request number or URL must never be reported for this repository until `tests/test_github_live.py` runs successfully against a real installation.