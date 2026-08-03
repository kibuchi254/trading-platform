# ATLAS Documentation

This is the canonical documentation for the ATLAS trading platform. Start here, then dive
into the area you need.

| Doc | Audience | What's in it |
|---|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Engineers, architects | Layering, the Bridge indirection, event bus, execution adapters, multi-tenancy, data model |
| [API.md](API.md) | Integrators, frontend | Full REST + WebSocket endpoint reference with request/response payloads |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Contributors | Local setup, testing, migrations, linting, project conventions |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Operators, SRE | Local, single-VM, Kubernetes, backups, DR, monitoring, troubleshooting |
| [SECURITY.md](SECURITY.md) | Everyone | Trust model, auth, secrets, responsible disclosure |
| [ATLAS-Architecture.pdf](ATLAS-Architecture.pdf) | All | The original design document |

## TL;DR

ATLAS is a multi-tenant, AI-native algorithmic trading platform. The **backend** (Python /
FastAPI) is the brain; an **MT5 Bridge** service carries a versioned JSON protocol over
WebSocket to MetaTrader 5 terminals (which run under Wine on the host); the **frontend**
(Next.js + shadcn) is the operator console. MT5 is treated as one of many pluggable
**execution adapters** — replacing the broker is a plugin change, not a platform change.

```
Browser ── /api ─► REST API (FastAPI :8000)
        ── /ws  ─► ticks / terminal-events
Terminal (EA) ── ws ─► Bridge Service (:9000) ──► Application (CQRS) ──► Domain + Risk + DB
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full picture.
