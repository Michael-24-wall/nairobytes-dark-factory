# Nairobytes Dark Factory Frontend

The frontend is a Vite + React + Tailwind console for the verified reservation system and its recorded factory evidence.

## Development

From the repository root:

```powershell
cd app/frontend
npm install
npm run dev
```

The Vite app runs at `http://127.0.0.1:5173`.

Start the backend separately:

```powershell
cd C:\Users\Michael\Desktop\BANDS\nairobytes-dark-factory
.venv\Scripts\python.exe -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8000
```

## Environment

Copy `.env.example` to `.env` when the API is not running at the default URL:

```text
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## Build and testing

```powershell
npm run build
cd ../..
.venv\Scripts\python.exe -m pytest tests -q
```

The backend suite remains at 46 passing tests with one existing non-failing warning.

## Architecture

- `src/api/` contains the shared fetch client and reservation operations.
- `src/data/evidence.js` imports the repository evidence files at build time with Vite's `?raw` loader.
- `src/App.jsx` owns the route-level console views and live demonstration workflows.
- `src/styles.css` contains the responsive dark factory visual system.

## API integration

Reservation Lab uses the real `POST /tables` and `POST /reservations` routes. Idempotency Lab performs real create, replay, and changed-payload requests. Timezone Lab sends real offset-bearing timestamps and displays the returned UTC values. The concurrency demo sends concurrent real reservation requests and counts actual HTTP status codes.

Project creation uses the real project API slice: `POST /projects`, `PUT /projects/{id}/design`, `POST /projects/{id}/assets`, and `GET /projects/{id}`. `/projects/new` stores requirements, project-specific design tokens, workspace metadata, and optional assets; `/projects/:id` reads the persisted record back.

The backend does not expose table listing, deletion, or database health routes. The UI does not invent them: table targets are provisioned through `POST /tables`, test reservations are labeled persistent, and database health is shown as `UNKNOWN`.

The Settings view exposes the local runtime contract and these boundaries as read-only information.