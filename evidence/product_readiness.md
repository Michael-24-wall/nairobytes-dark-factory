# Product Readiness

## Product scope

Nairobytes Dark Factory is presented as a general-purpose AI software engineering factory. The reservation system is labeled as the current verified tablekeeper example. Projects such as wallets, banking, inventory, healthcare scheduling, and enterprise workflows are explicitly marked `PLANNED` or `CONCEPT`.

## Delivered interface

- Product landing page at `/` with the factory message and proof chain.
- Dashboard at `/dashboard` using recorded factory evidence.
- Projects catalog at `/projects` separating verified and future tracks.
- Project creation at `/projects/new` with persisted requirements, design tokens, isolated workspace metadata, and backend asset upload support.
- Project detail at `/projects/:id` with real requirements, design, assets, workspace, and integration boundary state.
- Reservation product at `/reservations` with live creation, retrieval, provisioning, and conflict handling.
- Factory pipeline at `/factory` and recorded agent view at `/agents`.
- Dedicated live Idempotency, Timezone, and Concurrency Attack labs.
- Evidence Center reading approved repository evidence at build time.
- System Health with measured API status and honest database `UNKNOWN` status.
- Settings/About views explaining runtime boundaries and the factory method.

## Truthfulness boundaries

- Recorded test counts and agent states are labeled recorded evidence.
- Future project tracks are not presented as implemented systems.
- The frontend never connects directly to PostgreSQL.
- No arbitrary filesystem endpoint was added; evidence is a build-time approved manifest.
- No fake table availability or database row count is displayed where the backend has no corresponding route.

## Backend impact

Backend changes add the project/design/workspace/asset schema and routes plus CORS for the two local Vite origins and existing GET/POST/PUT methods. Reservation logic, PostgreSQL reservation invariants, concurrency protection, idempotency behavior, and timezone handling remain unchanged.

## Validation status

```text
Frontend production build: PASS
Backend regression: 46 passed, 1 warning
Full backend regression after project slice: 50 passed, 1 warning
Project API tests: 4 passed
Browser route sweep: 13 routes rendered
Live reservation create/retrieve: PASS
Live overlap conflict: PASS
Live idempotency: 201 -> 200 -> 409, PASS
Live timezone normalization: PASS
Live concurrency attack: 1 success, 7 replay, 0 failures, PASS
Mobile viewport check: 390x844, PASS
```

## Limitations

- PostgreSQL status cannot be independently reported by the frontend because no safe backend health route exists.
- The backend has no list or delete endpoint, so browser demonstration reservations remain persistent and are clearly labeled.
- Project creation and detail retrieval were browser-verified; browser asset upload still needs a clean non-overlapping runner pass, while the backend multipart path is covered by automated tests.
- Live BAND orchestration is unavailable; agent views use recorded evidence.
- The existing non-failing Starlette `httpx` deprecation warning remains.
- A dedicated automated frontend test runner was not added; browser validation was performed through the running UI.