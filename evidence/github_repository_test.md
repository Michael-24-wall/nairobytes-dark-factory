# Repository Listing And Creation Evidence

Date: 2026-10-03

## What was verified locally

Commands:

```text
.venv\Scripts\python.exe -m pytest tests/test_github.py -q
.venv\Scripts\python.exe -m pytest tests/test_github_api.py -q
```

Observed:

```text
28 passed in 10.33s
33 passed, 1 warning in 48.58s
```

## Listing

- `GitHubService.repositories()` calls `POST /app/installations/{id}/access_tokens`, then `GET /installation/repositories?per_page=100` with the installation token as a bearer token.
- Pagination follows the `Link` header with `rel="next"` and stops at the page cap, so a large installation cannot loop forever.
- `GET /api/github/repositories` returns only `id`, `name`, `full_name`, `owner`, `private`, `default_branch`, `archived`, and `permissions` for each repository. No token, no raw GitHub payload.
- An installation with no repositories returns `200` with an empty array. The backend does not fabricate rows.
- A revoked installation token produces `GITHUB_UNAUTHORIZED` with HTTP `502` instead of an empty list.
- Each repository is read back from GitHub with `GET /repos/{owner}/{name}` before it can be mapped to a project. If the returned repository ID differs from the submitted ID, the request is rejected with `409 GITHUB_REPOSITORY_MISMATCH`.

## Creation

`POST /api/github/repositories` calls `POST /orgs/{org}/repos` with an installation token.

- This is the only GitHub endpoint an App installation token can use to create a repository.
- For a personal account installation the backend refuses with `422 GITHUB_UNPROCESSABLE` and states the reason. No repository is created and nothing is recorded.
- Repository names are validated against `^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$` before any URL is built. Owner logins are validated the same way.
- The console only offers the form when `GET /api/github/status` reports `capabilities.create_repository = true`, which is derived from the installation account type returned by GitHub.

## Console

`/settings/github` renders the installation account, repository selection, capability chips, and the repository list exactly as returned by the backend. The create form is replaced by an explicit explanation when the installation is not an organization.

## Live status

`NOT CONFIGURED`. No GitHub App credentials or installation exist in this environment, so no repository was listed, created, or read on github.com. All HTTP responses in these tests are deterministic mocked GitHub responses. See `evidence/github_integration_test.md` for the full environment audit.