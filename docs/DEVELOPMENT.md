# ATLAS — Development

Local setup, testing, migrations, linting, and project conventions. For deployment, see
[DEPLOYMENT.md](DEPLOYMENT.md); for the data model and layers, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## 1. Prerequisites

- **Python 3.13+** and **[uv](https://github.com/astral-sh/uv)** (fast package manager)
- **[bun](https://bun.sh)** ≥ 1.3 (frontend)
- **Docker** + Docker Compose (for PostgreSQL, Redis, Flower)

---

## 2. Backend setup

```bash
# clone & install
git clone git@github.com:kibuchi254/trading-platform.git
cd trading-platform
uv venv --python 3.13
uv pip install -e ".[dev]"

# configure (set SECRET_KEY + BRIDGE_AUTH_TOKEN to long random strings)
cp .env.example .env

# start infra
docker compose -f docker/docker-compose.yml up -d postgres redis flower

# run migrations
alembic upgrade head
```

### Run the backend (three processes)

```bash
uvicorn platform.main:app --reload --port 8000            # REST API + WS
python -m platform.bridge.server --port 9000             # MT5 Bridge
celery -A platform.infrastructure.celery_app worker -l info
celery -A platform.infrastructure.celery_app beat -l info  # periodic tasks (optional)
```

The `atlas` CLI (`pyproject.toml → [project.scripts] atlas`) is available for admin tasks once installed.

---

## 3. Frontend setup

```bash
cd frontend
cp .env.example .env.local          # adjust if backend isn't on localhost:8000
bun install
bun run dev                         # http://localhost:3000
```

First sign-in: open `/auth/v1/register` to create your organization + first admin, or
`/auth/v1/login`. Interactive API docs at `http://localhost:8000/docs`.

### Frontend scripts
```bash
bun run dev       # next dev (Turbopack)
bun run build     # production build + type-check
bun run check     # biome lint/format
```

### Frontend layout
- `src/lib/api/` — REST client (`client.ts`), typed endpoints (`endpoints.ts`), DTOs (`types.ts`),
  WS client (`ws.ts`), data-fetching hook (`hooks.ts`).
- `src/app/api/auth/` — BFF route handlers (login/register/logout/refresh) that set auth cookies.
- `src/middleware.ts` — guards `/dashboard/*`.
- `src/app/(main)/dashboard/<area>/` — one folder per ATLAS domain.
- `src/navigation/sidebar/sidebar-items.ts` — sidebar nav config.
- `src/components/atlas/` — shared ATLAS UI (`MetricCard`, `PageHeader`, …) + `logo.tsx`.

---

## 4. Testing

```bash
pytest                            # all tests
pytest tests/unit/                # fast, no services (fakeredis; PG optional via service containers)
pytest tests/integration/         # real PostgreSQL + Redis, mocked Bridge
pytest tests/e2e/                 # full stack
pytest --cov=platform --cov-report=html   # coverage → htmlcov/index.html
pytest tests/unit/test_order_aggregate.py::test_order_starts_pending -v   # one test
```

- Framework: **pytest** + **pytest-asyncio** (`asyncio_mode = "auto"`).
- Mocking: `monkeypatch`, **respx** (HTTP), **fakeredis** (Redis).
- Coverage target: 80% (currently 68% and growing). Coverage is enforced in CI via `--cov-report=xml`.
- The `local_only_bus` fixture forces the event bus to run without Redis.
- `clean_registry` / `clean_risk_engine` reset the process-wide singletons between tests.

---

## 5. Linting & type-checking

### Backend
```bash
ruff check src/ tests/             # lint
ruff format --check src/ tests/    # format check (or ruff format src/ tests/ to apply)
mypy src/platform/                 # strict type-check (Pydantic plugin)
```
Config in `pyproject.toml` (`[tool.ruff]`, `[tool.mypy]`). mypy is currently non-blocking in CI;
fix incrementally.

### Frontend
```bash
cd frontend
bun run check       # biome check (lint + format)
bun run build       # TypeScript type-check via next build
```
Config in `frontend/biome.json`. Husky + lint-staged run `biome check --write` on commit.

---

## 6. Database migrations (Alembic)

```bash
alembic upgrade head                                # apply all
alembic downgrade -1                                # rollback one
alembic revision --autogenerate -m "add x to y"     # create a migration
```

### Migration rules (enforced by `pr-checks.yml`)
- Every migration **MUST** be backward-compatible (the previous version must still work).
- Never `DROP COLUMN` in the same release that stops using it — wait one release.
- If breaking, split into two migrations deployed across two releases.
- A migration without a paired test **fails CI**.

---

## 7. Project conventions

### Clean architecture (dependency direction, enforced in review)
- `domain/` — no imports from infrastructure or API.
- `application/` — may import domain + infrastructure interfaces.
- `infrastructure/` — may import domain + application.
- `api/` — may import application + infrastructure.

### The Wine rule
No code in `src/platform/` may `import wine`, `import subprocess` targeting `wine`, or
`import MetaTrader5`. All MT5 access goes through
`platform.infrastructure.mt5_bridge.client.BridgeClient`.

### Async-first
Every I/O function is `async def`. The only exception is Celery task wrappers (which call
`asyncio.run()` internally).

### Multi-tenancy
Every DB table that owns user data carries `org_id`. Every query path filters by `org_id` from
the `CurrentUser` dependency. Org-scoping is checked in code review.

### Code style
- Python 3.13 — use `match/case`, `X | None`, f-strings. Type hints required.
- Line length 100 (Ruff/Black). Imports sorted by Ruff.
- Docstrings on every public class/function/method.

### Conventional Commits
`feat:` / `fix:` / `perf:` / `refactor:` / `docs:` / `chore:` … — they drive
[semantic-release](https://python-semantic-release.readthedocs.io/) (`feat` → minor, `fix` →
patch, `feat!` / `BREAKING CHANGE` → major).

---

## 8. Adding things

### A strategy
1. Create `src/platform/strategies/builtin/your_strategy.py`.
2. Subclass `Strategy`, decorate with `@strategy`.
3. Implement `async def on_bar(self, bar, ctx) -> Signal | None`.
4. Add a test in `tests/unit/`.
5. Document parameters in the class docstring.

### An AI module
1. Create `src/platform/ai/modules/your_module.py`.
2. Subclass `AIModule`, implement `async def analyze(self, ctx) -> AIPrediction`.
3. Register with the orchestrator in `platform/main.py` lifespan.
4. Add a test.

### A risk rule
1. Create `src/platform/risk/rules/your_rule.py`.
2. Subclass `RiskRule`, implement `async def evaluate(self, ctx) -> None`.
3. Raise `RiskLimitBreached` to reject.
4. Register in `platform/risk/rules/__init__.py` via `register_all_rules()`.
5. Add a test (risk changes **require** tests — enforced in CI).

### An execution adapter
1. Subclass `ExecutionAdapter` (`infrastructure/execution/adapter_base.py`).
2. Register at import time: `get_adapter_registry().register("your_kind", YourAdapter)`.
3. No core code changes — the application layer uses `ExecutionAdapter` uniformly.

### A REST router
Follow `src/platform/api/v1/{terminals,orders}.py`: `APIRouter(prefix=..., tags=...)`,
`get_current_user`/`require_role` deps, Pydantic `Out` models with `from_attributes`, org-scoped
queries. Register the router in `src/platform/main.py` `api_v1` list.
