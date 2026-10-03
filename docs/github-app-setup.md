# GitHub App Setup

The GitHub App integration is implemented server-side. In this environment it is `NOT CONFIGURED`: no GitHub credentials, private key, or installation are present, so no live GitHub result is claimed anywhere in this repository.

## 1. Create the App

1. In GitHub, open **Settings → Developer settings → GitHub Apps → New GitHub App** under the account or organization that should own the repositories.
2. Set the App name, for example `Nairobytes Dark Factory`.
3. Set the homepage URL, for example `http://127.0.0.1:5173/settings/github` for local development.
4. Set the callback URL to the same value as `GITHUB_REDIRECT_URI` below.
5. Set the webhook URL to `<your backend>/api/github/webhook`, for example `http://127.0.0.1:8000/api/github/webhook`, content type `application/json`, and a strong secret. The secret becomes `GITHUB_WEBHOOK_SECRET`.
6. Subscribe to webhook events:
   - `Installation` — required to record installations and installation changes;
   - `Installation repositories` — recommended, keeps the recorded repository selection current;
   - `Pull request` — required to keep pull request state current after creation.
7. Set repository permissions:
   - **Metadata**: Read-only (mandatory for every installation);
   - **Contents**: Read and write (branch, commit, push);
   - **Pull requests**: Read and write (open and read pull requests);
   - **Administration**: Read-only, only if the installation should read the base branch default.
8. Set organization permissions to **Administration: Read and write** only if you want `POST /api/github/repositories` to create repositories. GitHub does not allow an App installation token to create a repository on a personal account; the backend rejects that case with `422 GITHUB_UNPROCESSABLE` instead of pretending it succeeded.
9. Where should the GitHub App be installed? Choose the account or organization. Save the App.
10. Generate a private key and download the `.pem` file. Its contents belong only in the server environment, never in the repository, the frontend, or evidence files.
11. Install the App: use **Install App** on the App page, or open the install URL that the backend reports at `GET /api/github/status` (`install_url`).
12. Note the installation ID from the URL fragment (`.../settings/installations/<installation_id>`) or from the signed `installation` webhook.

## 2. Configure the server

Copy `.env.example` values into your local `.env` (already ignored by git):

```text
GITHUB_APP_ID=123456
GITHUB_APP_NAME=Nairobytes Dark Factory
GITHUB_CLIENT_ID=Iv1.0123456789abcdef
GITHUB_CLIENT_SECRET=...
GITHUB_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----\n"
GITHUB_WEBHOOK_SECRET=...
GITHUB_REDIRECT_URI=http://127.0.0.1:5173/settings/github
GITHUB_INSTALLATION_ID=12345678
FACTORY_ADMIN_TOKEN=choose-a-long-random-value
```

Notes:

- `GITHUB_PRIVATE_KEY` accepts literal `\n` sequences, so the PEM can be stored on one line.
- `GITHUB_INSTALLATION_ID` is optional when the webhook is configured. The backend then uses the installation recorded by the signed webhook. Without either, `/api/github/status` reports `NOT_CONNECTED`.
- `GITHUB_WEBHOOK_SECRET` is optional for read-only use, but without it `/api/github/webhook` returns `503` and installations are never recorded automatically.
- `FACTORY_ADMIN_TOKEN` is required. Every `/api/github/*` route except the webhook requires `X-Factory-Admin-Token` with that exact value, compared with `secrets.compare_digest`. A missing server value returns `503`; a wrong value returns `401`.
- Optional overrides: `GITHUB_APP_SLUG`, `GITHUB_API_BASE_URL`, `GITHUB_WEB_BASE_URL`, `GITHUB_TIMEOUT_SECONDS`.

## 3. Configure the frontend proxy

`FACTORY_ADMIN_TOKEN` must reach FastAPI without entering the browser bundle. The Vite dev and preview servers read it from the process environment and inject it as `X-Factory-Admin-Token` on `/api/github` requests only:

```powershell
$env:FACTORY_ADMIN_TOKEN = "choose-a-long-random-value"
npm run dev
```

Never put the token in a `VITE_*` variable. Without the proxy value the browser receives `401` for every GitHub route, and the UI reports that state instead of faking data.

## 4. Verify the connection

1. Start the backend and confirm the health probe used by the UI: `GET /docs`.
2. Authenticated: `GET /api/github/status`. Expected results:
   - `200` with `"status": "CONNECTED"` and the real account, repository count, permissions, and capabilities;
   - `200` with `"status": "NOT_CONNECTED"` when the App is configured but not installed;
   - `503` when the App configuration is missing;
   - `502`/`504` when GitHub cannot be reached or times out.
3. Authenticated: `GET /api/github/repositories` lists only repositories the installation can reach.
4. Authenticated: `GET /api/github/installations` lists installations recorded from signed webhooks.

## 5. Use the integration

1. Open **Settings → GitHub Integration** in the console. The page shows the real installation state, capabilities, installations, and repositories.
2. Open a project, then **Open GitHub publishing**. Select a repository from the installation and link it. The backend re-reads the repository with the installation token and rejects a mismatch with `409 GITHUB_REPOSITORY_MISMATCH`.
3. Run a factory run for that project and let it reach `awaiting_approval` or `approved`. Only those run states can be published; anything else returns `409 GITHUB_RUN_NOT_PUBLISHABLE`.
4. **Push to factory branch** publishes the real artifact bytes from the project workspace to `factory/project-{project_id}/run-{run_id}`. The default branch is not modified. The only exception is an empty repository, which is initialised with a single README commit so a branch can exist.
5. **Open pull request** opens a real pull request from the factory branch into the mapped default branch. The body is generated from the recorded tasks, artifacts, pushed files, commit, and approval state. Opening a second pull request for the same run returns `409 GITHUB_PULL_REQUEST_EXISTS`.
6. **Refresh from GitHub** re-reads the pull request from the API and records `state`, `merged`, `changed_files`, and `commits`.

## Known limitations

- Repository creation works only for organization installations. Personal installations receive `422` with an explanation.
- The admin token is a single shared development gate. It is not a user identity system, and it does not separate two different admin users from each other.
- The frontend only works through the Vite proxy described above. A static deployment must provide an equivalent reverse proxy.
- The live test suite is opt-in and was not executed in this environment, so live push and pull request behaviour is `NOT TESTED` here. See `evidence/github_git_flow_test.md`, `evidence/github_pull_request_test.md`, and `tests/test_github_live.py`.
