# Project Generation

## Implemented vertical slice

`/projects/new` collects:

- project name, description, type, users, domain
- functional and non-functional requirements
- technology and database preferences
- authentication requirement as configuration data
- per-project color tokens, visual style, theme, and custom design instructions
- an optional real logo/image/document upload with alt text, asset type, and section assignment

Creation calls `POST /projects`, persists the design with `PUT /projects/{id}/design`, and uploads the selected file with `POST /projects/{id}/assets`. The resulting `/projects/:id` page reads the record back from the backend.

## Not yet implemented

The project record is not yet handed to an Architect/Builder execution worker. Generated project files, tests, Breaker tasks, Verifier records, Git operations, GitHub, deployment, and human approval persistence are future factory stages. The UI labels these boundaries instead of presenting them as live.