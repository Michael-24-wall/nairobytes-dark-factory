# UI End-to-End Test Evidence

## Setup

Backend:

```text
.venv\Scripts\python.exe -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8000
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

Frontend:

```text
npm run dev -- --host 127.0.0.1
VITE v6.4.3  ready
Local: http://127.0.0.1:5173/
```

## Build and regression

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

## Browser checks

Using the running Vite app and FastAPI backend, the following routes loaded with a visible main view at 1440x900:

```text
/, /dashboard, /projects, /reservations, /factory, /idempotency,
/timezone, /attacks, /agents, /evidence, /health, /settings, /about
```

The landing page rendered the product message `Build software. Break it. Verify it. Ship with evidence.` and an operational `BACKEND ONLINE` state. The landing page also rendered at 390x844 with the mobile navigation control and visual intact.

Reservation flow:

- Provisioned/used a real table target through the UI.
- Created a real reservation through `POST /reservations`, receiving HTTP `201` and a reservation ID.
- Clicked `Retrieve by ID`, which called `GET /reservations/{id}` and confirmed the same reservation.
- Submitted a second overlapping request with a different key and received the handled message: `Reservation rejected: this table is already reserved for that time window.` The API response was HTTP `409`.

Idempotency flow:

```text
FIRST REQUEST       HTTP 201
IDENTICAL REPLAY   HTTP 200
DIFFERENT PAYLOAD  HTTP 409 IDEMPOTENCY_PAYLOAD_MISMATCH
```

The replay displayed the same reservation ID.

Timezone flow:

```text
CLIENT TIME  2026-06-04T20:00:00+02:00
RETURNED UTC 2026-06-04T18:00:00+00:00
```

Concurrency flow:

```text
8 requests completed
1 successful reservation
7 idempotent replay
0 rejected conflicts
0 server failures
RECORDED PASS
```

All eight attack requests intentionally used the same idempotency key. The UI counts the actual HTTP status returned by each request.

Health and evidence:

- System Health showed the API as `ONLINE` from a real `GET /docs` probe.
- PostgreSQL was shown as `UNKNOWN` because the backend exposes no database health endpoint.
- Evidence Center loaded the repository evidence manifest and rendered the real document contents.

## Expected network events

The browser console recorded HTTP 409 network entries during the intentional overlap/conflict demonstration. The UI caught and rendered these responses as user-facing conflict states; no uncaught application error occurred.