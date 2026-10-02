# Architecture

The repository currently has two bounded surfaces:

1. The verified reservation workload, backed by FastAPI, psycopg, PostgreSQL, a GiST exclusion constraint, idempotency keys, and per-table advisory locking.
2. The factory project-definition slice, backed by PostgreSQL tables for projects, design tokens, workspaces, and assets.

The React/Vite frontend calls FastAPI through `src/api/`. It never connects directly to PostgreSQL. Evidence is imported from an approved build-time manifest rather than exposing arbitrary filesystem paths.

Project assets are stored below `FACTORY_WORKSPACE_ROOT` (defaulting to the local temp directory) under a UUID project directory. URLs are project/asset scoped and are checked against the resolved workspace root before serving.