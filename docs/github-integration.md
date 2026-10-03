# GitHub Integration

The repository contains a complete, real GitHub App integration. It is not a mock and it is not a status display: the backend signs an App JWT, exchanges it for a short-lived installation access token, reads installations and repositories from `api.github.com`, pushes real commits with `git`, and opens real pull requests.

## What is implemented

| Capability | Where | Behaviour |
| --- | --- | --- |
| App authentication | `app/backend/github_service.py` | RS256 App JWT, per-installation token cache, no long-lived token |
| Installation discovery | `github_service.py`, `github_api.py` | `GET /app/installations/{id}`, recorded installations, signed webhook |
| Repository listing | `github_service.py` | Paginated `/installation/repositories`, capped pages |
| Repository creation | `github_service.py` | `POST /orgs/{org}/repos`; personal installations are rejected honestly |
| Repository mapping | `github_api.py` | Re-reads the repository with the installation token and rejects identity mismatch |
| Publishing | `app/backend/git_flow.py` | Real branch, commit, push, and remote SHA verification through `git` |
| Pull requests | `github_service.py`, `github_api.py` | Real create, real read-back, recorded state, webhook updates |
| Webhooks | `github_api.py` | HMAC-SHA256 verification of `installation`, `installation_repositories`, `pull_request` |
| Console | `app/frontend/src/App.jsx` | Installation status, capabilities, repositories, mapping, publish, pull request |

## Request flow

1. An administrator installs the App on GitHub and configures the server values in `docs/github-app-setup.md`.
2. `GET /api/github/status` reports what GitHub actually returns for the recorded installation.
3. A project is mapped to one repository with `POST /api/github/projects/{project_id}/connect`.
4. A verified factory run is published with `POST /api/github/projects/{project_id}/runs/{run_id}/publish`. The generated artifact bytes are read from the project workspace and pushed to `factory/project-{project_id}/run-{run_id}`.
5. `POST /api/github/projects/{project_id}/runs/{run_id}/pull-request` opens a real pull request from that branch into the mapped default branch, and `GET` on the same path refreshes the recorded state from GitHub.

## Recorded state

`github_installations`, `project_github_integrations`, `git_commits`, and `github_pull_requests` hold the installation, mapping, push, and pull request records. Factory events of type `github_push` and `github_pull_request` are written into the same run timeline as the agent stages, so the UI never has to invent history.

## Current status in this environment

No GitHub credentials, private key, installation, `gh` CLI, or `.env` file exist here, so:

- read-only and write live verification: `NOT CONFIGURED`;
- live tests: `NOT TESTED` (they skip unless explicitly enabled);
- all local verification uses deterministic mocked GitHub HTTP responses and a real local bare git remote. That proves the code paths, not live GitHub activity.

See `evidence/github_integration_test.md`, `evidence/github_repository_test.md`, `evidence/github_git_flow_test.md`, `evidence/github_pull_request_test.md`, and `evidence/github_security_test.md`.

## Boundaries

- No personal-account repository creation is possible through a GitHub App; the backend says so instead of failing silently.
- The shared `FACTORY_ADMIN_TOKEN` gate is a development control, not user-level authorization.
- Deployment, hosting, and issue tracking are outside this system.