# Security Boundary

## General

- The browser never receives database credentials or service secrets.
- The asset endpoint accepts only a small allowlist of image/PDF MIME types and limits files to 10 MB.
- Uploaded filenames are reduced to their basename and stored under a generated UUID filename.
- Asset serving checks the resolved path remains inside the configured workspace root.
- No arbitrary command execution endpoint exists.

## GitHub App

- The GitHub private key, client secret, and webhook secret are read from the server environment only. They are never returned by any route, never sent to the browser, and never written to evidence or logs.
- Every `/api/github/*` route except the webhook requires `X-Factory-Admin-Token`, compared with `secrets.compare_digest`. A missing server value yields `503`; a wrong or absent header yields `401`.
- The admin token is injected by the Vite dev/preview proxy from the process environment. No `VITE_*` variable contains a secret, so a production bundle cannot leak it.
- Installation access tokens are generated per installation, cached in memory only for their lifetime, and never persisted or returned.
- Git pushes authenticate through `GIT_ASKPASS` scripts in a temporary directory. Tokens never appear in a command line, a remote URL, or captured output; output is scrubbed before any error is raised or recorded.
- Published file paths are resolved and rejected if they escape the temporary publish directory.
- GitHub webhook payloads are accepted only with a valid `X-Hub-Signature-256` HMAC-SHA256 signature over the raw body. Without a configured webhook secret the route returns `503` and accepts nothing.
- User-supplied owner, repository, branch, and run values are validated against strict patterns before any URL is built. Path traversal and `..` ref segments are rejected.
- GitHub error bodies are reduced to a single sanitized line, and known credential values are replaced with `[redacted]` before the message is returned.

## Authorization limits

`FACTORY_ADMIN_TOKEN` is a single shared development gate. It proves a caller knows the server secret; it does not distinguish users or projects, and any holder can read or modify any project's GitHub mapping. The current project API has no per-user authorization either. Both must be treated as development-only boundaries until real authentication and backend access control exist.

## Deployment limits

Deployment credentials, authentication providers, and hosting integrations are outside this system and are not configured.