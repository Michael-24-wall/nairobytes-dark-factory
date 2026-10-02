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
- About Factory: factory method and human-acceptance principle.

## API and backend changes

The frontend uses the existing `/tables`, `/reservations`, and `/reservations/{id}` routes. The only backend change is localhost CORS for the Vite development origin (`127.0.0.1:5173` and `localhost:5173`) with the existing GET/POST methods. No reservation logic, schema, or tests were changed.

## Observed validation

```text
npm install @tanstack/react-query
added 2 packages, audited 139 packages
found 0 vulnerabilities

npm run build
vite v6.4.3 building for production...
✓ 1645 modules transformed.
✓ built in 5.19s

.venv\Scripts\python.exe -m pytest tests -q
46 passed, 1 warning in 24.39s
```

Browser validation against the running backend and frontend observed:

- Dashboard API status: `ONLINE`.
- Live reservation response: HTTP 201 with reservation ID, table, UTC timestamps, created timestamp, and active status.
- Idempotency Lab: HTTP `201`, `200`, and `409 IDEMPOTENCY_PAYLOAD_MISMATCH`; replay ID matched.
- Timezone Lab: `2026-06-04T20:00:00+02:00` returned as `2026-06-04T18:00:00+00:00`.
- Routes loaded successfully: Factory Run, Reservation Lab, Idempotency Lab, Timezone Lab, Agent Pipeline, Evidence Center, System Health, Settings, and About.
- Mobile dashboard inspected at 390x844 with no visible horizontal layout break.

## Known limitations

- Live BAND agent activity is not available, so agent cards are explicitly recorded status.
- The backend has no table listing or reservation deletion endpoint; the UI does not fake either capability.
- Browser demo requests create real persistent test reservations because the backend has no safe deletion route.
- The existing Starlette `httpx` deprecation warning remains.