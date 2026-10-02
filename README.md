# Nairobytes Dark Factory

Nairobytes Dark Factory is an AI software engineering factory concept that turns requirements into software through architecture, implementation, testing, adversarial verification, evidence, and human approval.

## Current implementation

The verified reservation workload remains available under the React frontend at `/reservations`, `/idempotency`, `/timezone`, and `/attacks`. The first general-purpose factory vertical slice is also live:

- `POST /projects` creates a persisted project and isolated workspace metadata.
- `PUT /projects/{id}/design` stores project-specific design tokens and style/theme preferences.
- `POST /projects/{id}/assets` validates and stores real image/document assets under the project workspace.
- `GET /projects/{id}` returns requirements, design, workspace, and assigned assets.
- `/projects/new` provides a real requirements, design/branding, and asset upload wizard.
- `/projects/:id` displays the persisted project record and integration boundaries.

Factory execution, generated-project Builder tasks, authentication, GitHub, deployment, secrets, and admin authorization are not implemented in this slice and are labeled `PLANNED` or `NOT CONFIGURED` in the UI.

## Local development

Backend:

```powershell
.venv\Scripts\python.exe -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
cd app/frontend
npm install
npm run dev
```

See [app/frontend/README.md](app/frontend/README.md) and [docs/project-generation.md](docs/project-generation.md) for the current contract.
