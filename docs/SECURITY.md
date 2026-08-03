# ATLAS — Security

This document describes the trust model, authentication, authorization, secrets handling, and
responsible disclosure for ATLAS.

---

## Trust model

- **The backend is the trust boundary.** Every REST/WS request is authenticated and authorized
  server-side. The frontend is a **thin client** — it holds a short-lived JWT, but the backend
  re-validates it and re-scopes every query by `org_id`.
- **The MT5 terminal is a semi-trusted edge device.** It authenticates to the Bridge with a
  shared `BRIDGE_AUTH_TOKEN` (out-of-band). The Bridge never trusts terminal-supplied identifiers
  for authorization — the backend resolves `org_id` from the authenticated user, not from the EA.
- **Wine/MT5 is untrusted from the backend's perspective.** The backend never shells out to
  `wine` or `mt5.exe` (the Wine rule), so a compromised Wine host cannot inject code into the
  platform process.

---

## Authentication

Two methods, resolved from request headers (`core/dependencies.py`):

| Method | Header | Lifetime |
|---|---|---|
| JWT (access) | `Authorization: Bearer <jwt>` | 15 minutes (`JWT_ACCESS_TTL_SECONDS`) |
| JWT (refresh) | `POST /auth/refresh` body | 30 days (`JWT_REFRESH_TTL_SECONDS`) |
| API key | `X-API-Key: atlas_<random>` | Optional expiry; rotated by the user |

- JWTs are HS256 signed with `SECRET_KEY`. `SECRET_KEY` must be ≥ 16 chars (validated at startup).
- API keys: the raw key is shown **once** on creation; only a bcrypt hash and an 8-char
  `key_prefix` are persisted. Verification uses constant-time bcrypt comparison.
- WebSocket endpoints authenticate via `?token=<jwt>` (WS cannot set headers).

## Authorization (RBAC)

Roles: `admin`, `trader`, `viewer`, `bot`. `require_role(...)` gates sensitive endpoints
(e.g. `POST /risk/kill-switch/release` is admin-only). The `CurrentUser` dependency carries
`org_id`, `user_id`, `role`, `scopes`.

## Multi-tenancy

Every tenant-owned table carries `org_id`. Every query path filters by `org_id` from
`CurrentUser`. A request for a resource in another org returns 404 (not 403) — no information
leakage about resource existence.

## Frontend (admin console)

- The console authenticates through a Next.js BFF (`/api/auth/{login,register,refresh,logout}`).
- Access + refresh tokens are stored in **JS-readable cookies** so SSR middleware can guard
  `/dashboard/*` **and** the WS client can append `?token=`. This is an auth *gate*, not a
  secrecy boundary — the backend re-validates the JWT on every request. Cookies are
  `Secure` in production, `SameSite=Lax`.
- Raw passwords never touch `localStorage`; the BFF proxies the backend and issues cookies.

## Secrets

- All secrets come from environment variables (`.env`), never from code.
- `SecretStr` (Pydantic) prevents accidental logging of `SECRET_KEY`, `BRIDGE_AUTH_TOKEN`,
  `LLM_API_KEY`, DB/Redis passwords, SMTP/Telegram/Discord credentials.
- CI secrets: `SSH_*`, `GHCR_TOKEN`, `CODECOV_TOKEN`, `RELEASE_TOKEN` — injected via GitHub
  Actions secrets, never written to logs (`cd.yml` injects them as env vars over SSH).
- `.env` and `.env.production` are gitignored. The repo ships only `.env.example` with
  placeholder values (`change-me-*`).

## Audit

Sensitive actions write to the append-only `audit_logs` table (`actor_id`, `actor_type`,
`action`, `resource_type`, `resource_id`, `ip`, `user_agent`, `payload`, `ts`). View via
`GET /admin/audit-logs` (admin only).

## Security CI

- **bandit** static analysis on `src/platform/` → SARIF uploaded to the GitHub Security tab.
- **pip-audit --strict** for dependency CVEs.
- Images are built multi-arch, pushed to GHCR, and **attested** for build provenance
  (`attest-build-provenance`).
- CODEOWNERS routes `risk/` and `strategies/` to `@atlas-team/quant` review; `alembic/` and
  `deploy/` to `@atlas-team/infra`.

## Operational safety

- **Kill switch** (`/risk/kill-switch/engage`) blocks all new orders globally — a single button
  to stop the system.
- **Flatten** (`/terminals/{id}/flatten`) closes all positions + cancels all orders on a
  terminal — the emergency egress per terminal.
- **DR drill** (`scripts/dr_drill.sh`) simulates API/Bridge/Redis failures, DB backup, and kill
  switch engagement. Run quarterly in prod, monthly in staging.

---

## Responsible disclosure

Found a security issue? Please **do not** open a public issue. Email the maintainers privately
with a description and repro. We will acknowledge within 48 hours and work with you on a fix and
coordinated disclosure.

## Hardening checklist (production)

- [ ] `SECRET_KEY` and `BRIDGE_AUTH_TOKEN` are long random strings (≥ 32 chars).
- [ ] `ENV=production`; `/docs` and `/redoc` are disabled.
- [ ] CORS (`CORS_ORIGINS`) lists only the console origin(s).
- [ ] TLS terminates at nginx; `wss://` for the Bridge behind the proxy.
- [ ] PostgreSQL/Redis are not exposed publicly; only nginx :443 is.
- [ ] `LLM_PROVIDER` set only if an LLM assistant is desired; `LLM_API_KEY` populated.
- [ ] Automated DB backups (`scripts/backup_db.sh`) + optional S3 upload.
- [ ] GitHub `production` environment has required reviewers (deploy approval gate).
