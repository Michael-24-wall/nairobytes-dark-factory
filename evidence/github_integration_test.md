# GitHub Integration Evidence

Date: 2026-10-03

## What was verified locally

Command:

```text
.venv\Scripts\python.exe -m pytest tests -q
```

Observed:

```text
..........ssss.......................................                    [100%]
121 passed, 4 skipped, 1 warning in 107.64s (0:01:47)
```

The 4 skipped tests are the opt-in live GitHub tests described at the end of this file.

GitHub-specific suites, run individually:

| Command | Result |
| --- | --- |
| `.venv\Scripts\python.exe -m pytest tests/test_github.py -q` | `28 passed in 10.33s` |
| `.venv\Scripts\python.exe -m pytest tests/test_github_api.py -q` | `33 passed, 1 warning in 48.58s` |
| `.venv\Scripts\python.exe -m pytest tests/test_github_git_flow.py -q` | `8 passed in 19.40s` |
| `.venv\Scripts\python.exe -m pytest tests/test_github_live.py -q -rs` | `4 skipped in 0.26s` |

The single warning is the pre-existing `StarletteDeprecationWarning` about `httpx` in `fastapi.testclient`, unrelated to this work.

Note on the test command: the repository root contains a pre-existing, unrelated `test_band_opencode.py` that imports `band_sdk`, which is not installed. A bare `pytest` at the root therefore fails during collection. The suite for this project is `pytest tests`, which is what the numbers above use.

## What these tests actually exercise

`tests/test_github.py` — service level, against mocked GitHub HTTP:

- an App JWT is signed with the configured RSA key, expires in 600 seconds, and uses `iss` = app ID;
- installation tokens are requested once per installation and reused while valid;
- repository listing follows `Link: rel="next"` pagination and stops at the page cap;
- GitHub `401/403/404/409/422/429/500` map to distinct coded errors with correct HTTP status;
- timeouts become `GITHUB_TIMEOUT`/504 and connection failures become `GITHUB_BAD_GATEWAY`/502;
- known credential values are replaced with `[redacted]` in any message returned to a caller;
- organization repository creation is accepted, and a personal installation is rejected with `GITHUB_UNPROCESSABLE`;
- pull request creation and branch existence use the expected GitHub paths;
- clone URL building rejects path traversal;
- webhook HMAC comparison accepts a valid signature and rejects an invalid one.

`tests/test_github_api.py` — HTTP surface end to end, with mocked GitHub and a **real local bare git remote**:

- every `/api/github/*` route except the webhook returns `401` without the admin token, and `401` for a wrong token;
- `GET /status` reports `CONNECTED` with the real installation account, permissions, and capabilities derived from the GitHub response;
- `GET /repositories` returns the installation repositories, and an empty array when the installation has none;
- a revoked installation token surfaces as `GITHUB_UNAUTHORIZED`/502 rather than a silent empty list;
- GitHub timeouts surface as `GITHUB_TIMEOUT`/504 and a GitHub `500` as `GITHUB_BAD_GATEWAY`/502, with no stack trace or documentation URL in the response;
- `POST /connect` verifies the repository identity against GitHub and refuses a repository that is not reachable from the installation;
- `DELETE /projects/{id}` disconnects the mapping and a second delete returns `404`;
- publishing rejects runs that are not verified (`GITHUB_RUN_NOT_PUBLISHABLE`), rejects a project with no linked repository, and rejects a pull request for an unpublished run (`GITHUB_NOT_PUBLISHED`);
- the publish path pushes real files to a real branch in a real bare repository, records the push and a `github_push` factory event, and reports the remote URL;
- a real pull request record is created, and `GET` on the same path refreshes it from GitHub (`state`, `merged`, `changed_files`);
- a deleted pull request is reported as `GITHUB_NOT_FOUND`/404;
- webhook handling without a configured secret returns `503`; an unsigned or wrongly signed payload returns `401`;
- signed `installation` and `pull_request` webhooks record the installation and update the stored pull request state.

`tests/test_github_git_flow.py` — real `git`, real temporary repository, real push:

- files land on `factory/project-{id}/run-{id}` and the remote SHA matches the local commit;
- the default branch is not modified;
- an existing factory branch is reused instead of failing;
- an empty remote is initialised with one README commit on the default branch, then the factory branch is pushed;
- a generated path that escapes the publish directory is rejected as `GIT_UNSAFE_PATH`.

## Frontend build

```text
cd app\frontend
npm run build
```

Observed:

```text
vite v6.4.3 building for production...
transforming...
1653 modules transformed.
dist/index.html                   0.47 kB
dist/assets/index-BsJvyKIo.css   47.99 kB
dist/assets/index-DF6JDyBN.js   375.24 kB
built in 3.85s
```

The build proves the console compiles. It does not prove a live GitHub connection, because no browser session in this environment holds a configured installation.

## Live status

Environment audit on 2026-10-03:

```text
GITHUB_APP_ID=NOT_SET
GITHUB_APP_NAME=NOT_SET
GITHUB_CLIENT_ID=NOT_SET
GITHUB_CLIENT_SECRET=NOT_SET
GITHUB_PRIVATE_KEY=NOT_SET
GITHUB_WEBHOOK_SECRET=NOT_SET
GITHUB_REDIRECT_URI=NOT_SET
GITHUB_INSTALLATION_ID=NOT_SET
FACTORY_ADMIN_TOKEN=NOT_SET
GITHUB_TOKEN=NOT_SET
GH_TOKEN=NOT_SET
.env=ABSENT
gh CLI=NOT INSTALLED
git=2.55.0.windows.2
```

Therefore:

- live GitHub installation: **NOT CONFIGURED**;
- live repository listing or creation: **NOT CONFIGURED**;
- live push and pull request: **NOT CONFIGURED**;
- live GitHub verification: **NOT TESTED**, because `tests/test_github_live.py` requires `NAIROBYTES_LIVE_GITHUB=1` and real credentials, and neither exists here.

No claim in this repository asserts live GitHub activity. All GitHub HTTP responses used in the tests are deterministic mocked responses; the git pushes are real, but against a local bare repository on `file://`, not github.com.

## Implemented routes

- `GET /api/github/status`
- `GET /api/github/installations`
- `GET /api/github/repositories`
- `POST /api/github/repositories`
- `GET /api/github/projects/{project_id}`
- `POST /api/github/projects/{project_id}/connect`
- `DELETE /api/github/projects/{project_id}`
- `POST /api/github/projects/{project_id}/runs/{run_id}/publish`
- `POST /api/github/projects/{project_id}/runs/{run_id}/pull-request`
- `GET /api/github/projects/{project_id}/runs/{run_id}/pull-request`
- `POST /api/github/webhook`
- `GET /api/github/webhook`

All except the webhook require `X-Factory-Admin-Token` matching the server-side `FACTORY_ADMIN_TOKEN`. Private keys, client secrets, and installation tokens never appear in a response, in the frontend bundle, or in this evidence.