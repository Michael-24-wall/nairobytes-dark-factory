# UI Build Evidence

## Stack

- React 18
- Vite 6
- Tailwind CSS 3
- React Router 7
- TanStack React Query
- lucide-react
- JavaScript/JSX, no TypeScript

## Pages

- Dashboard: recorded 46/46 verification state, pipeline, metrics, and evidence timeline.
- Factory Run: stage-by-stage recorded execution view.
- Reservation Lab: live table provisioning, reservation creation, response details, and concurrent requests.
- Idempotency Lab: live `201 -> 200 -> 409` replay/mismatch sequence.
- Timezone Lab: live offset input and UTC response normalization.
- Agent Pipeline: recorded Architect, Builder, Breaker, and Verifier status.
- Evidence Center: build-time viewer for real files under `evidence/`.
- System Health: real frontend/API reachability, with database health honestly marked unknown.
- Settings: read-only local runtime configuration and explicit product boundaries.
- GitHub Integration (`/settings/github`): real installation status, capability chips, webhook-recorded installations, accessible repositories, and organization repository creation.
- Project GitHub publishing (`/projects/{id}/github`): repository linking, factory-branch push, pull request creation and read-back, and recorded push history.
- About Factory: factory method and human-acceptance principle.

## API and backend changes

The frontend uses the existing `/tables`, `/reservations`, and `/reservations/{id}` routes. The only backend change is localhost CORS for the Vite development origin (`127.0.0.1:5173` and `localhost:5173`) with the existing GET/POST methods. No reservation logic, schema, or tests were changed.

GitHub routes are called through a same-origin Vite proxy on `/api/github`. The proxy reads `FACTORY_ADMIN_TOKEN` from the process environment and adds `X-Factory-Admin-Token` on the way to FastAPI, so no secret is bundled. Everything else still uses `VITE_API_BASE_URL`.

## Observed validation

```text
npm install @tanstack/react-query
added 2 packages, audited 139 packages
found 0 vulnerabilities

npm run build
vite v6.4.3 building for production...
✓ 1653 modules transformed.
✓ built in 3.97s

.venv\Scripts\python.exe -m pytest tests -q
121 passed, 4 skipped, 1 warning in 103.62s
```

Browser validation against the running backend and frontend observed:

- Dashboard API status: `ONLINE`.
- Live reservation response: HTTP 201 with reservation ID, table, UTC timestamps, created timestamp, and active status.
- Idempotency Lab: HTTP `201`, `200`, and `409 IDEMPOTENCY_PAYLOAD_MISMATCH`; replay ID matched.
- Timezone Lab: `2026-06-04T20:00:00+02:00` returned as `2026-06-04T18:00:00+00:00`.
- Routes loaded successfully: Factory Run, Reservation Lab, Idempotency Lab, Timezone Lab, Agent Pipeline, Evidence Center, System Health, Settings, and About.
- Mobile dashboard inspected at 390x844 with no visible horizontal layout break.

GitHub pages were verified by build and by the backend API contract tests, not by a browser session with a configured installation. In this environment the GitHub console renders `NOT CONFIGURED`, because `FACTORY_ADMIN_TOKEN` and all `GITHUB_*` values are absent.

## Known limitations

- Live BAND agent activity is not available, so agent cards are explicitly recorded status.
- The backend has no table listing or reservation deletion endpoint; the UI does not fake either capability.
- Browser demo requests create real persistent test reservations because the backend has no safe deletion route.
- GitHub pages need the Vite proxy with `FACTORY_ADMIN_TOKEN` in the shell environment. Without it every GitHub route returns `401` and the console says so instead of showing invented data.
- The existing Starlette `httpx` deprecation warning remains.