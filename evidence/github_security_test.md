# GitHub Security Evidence

Date: 2026-10-03

## What was verified locally

Commands:

```text
.venv\Scripts\python.exe -m pytest tests/test_github.py -q
.venv\Scripts\python.exe -m pytest tests/test_github_api.py -q
.venv\Scripts\python.exe -m pytest tests/test_github_git_flow.py -q
```

Observed:

```text
28 passed in 10.33s
33 passed, 1 warning in 48.58s
8 passed in 19.40s
```

## Administrative authorization

- Every `/api/github/*` route except the webhook requires the `X-Factory-Admin-Token` header. Without it, or with a wrong value, the response is `401`. The test asserts this for every route, including project state, connect, disconnect, publish, and both pull request routes.
- The comparison uses `secrets.compare_digest`, so it is not a timing-oracle on the token.
- If `FACTORY_ADMIN_TOKEN` is not set on the server, the route returns `503` and no GitHub request is made. A missing server configuration cannot degrade into an open endpoint.
- A request without the header cannot read another project's GitHub state, mapping, push history, or pull request. The tests cover both projects under the same server.

Known limit, stated plainly: the admin token is a single shared secret. It authenticates a caller as "someone who knows the server secret", not as a particular user. Any holder can read or modify every project's mapping. That is a development control, not user-level authorization, and it is documented as such in `docs/security.md`.

## Credential exposure

- The App private key, client secret, and webhook secret are read from the environment and are never included in any response body. No route returns them, and no frontend module requests them.
- Installation tokens exist only in memory for the token lifetime and are never returned, logged, or persisted.
- A GitHub error body is reduced to a single sanitized line with newlines removed, unsafe characters replaced, and the length capped. A GitHub `500` response returns no stack trace and no `documentation_url`.
- Known credential values are replaced with `[redacted]` before a message leaves the service. A dedicated test returns a GitHub error that echoes both the real installation token and the client secret and asserts that neither appears and that `[redacted]` is present.
- The frontend cannot hold the admin token: it is injected by the Vite dev/preview proxy from the process environment, and no `VITE_*` variable contains a secret.
- No token appears in a git command line, remote URL, or captured output. Pushes authenticate through a temporary `GIT_ASKPASS` script and all captured output is scrubbed before use.

## Input validation

- Owner logins, repository names, and installation IDs are validated against strict patterns before any URL is built.
- Branch names are rejected if any segment contains `..` or starts with `.`, which blocks ref traversal.
- Clone URL construction rejects path traversal such as `../../etc`.
- Generated artifact paths are resolved and rejected with `GIT_UNSAFE_PATH` if they escape the publish directory or are absolute.

## Webhook authenticity

- `POST /api/github/webhook` verifies `X-Hub-Signature-256` as an HMAC-SHA256 over the raw request body using `GITHUB_WEBHOOK_SECRET`, compared with `secrets.compare_digest`.
- Without a configured secret the route returns `503`. An absent or incorrect signature returns `401`. A valid signature is the only accepted path.
- The webhook route intentionally does not require the admin token, because GitHub calls it, and it is safe because of the signature check.

## Rate limiting and availability

- GitHub `429` responses are translated into a coded error that preserves the `Retry-After` value without leaking the body.
- Request timeouts become `504 GITHUB_TIMEOUT`; connection failures become `502 GITHUB_BAD_GATEWAY`. Neither returns internal hostnames.

## Not verified here

- No live GitHub request was made, so no live rate limit, no real installation permission boundary, and no real GitHub-side authorization decision was observed. Those remain `NOT TESTED`.
- There is no per-user or per-project authorization in this system, and no deployment hardening, TLS termination, or secret manager integration. This is a local development boundary.