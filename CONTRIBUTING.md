# ATLAS — Contributing Guide

Thanks for contributing to ATLAS! This guide covers setup, conventions, and the PR process.
Also read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the layering and the Wine rule,
and [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for the full local setup.

## Development Setup

### Backend (Python 3.13 + uv)

```bash
git clone git@github.com:kibuchi254/trading-platform.git
cd trading-platform

uv venv --python 3.13
uv pip install -e ".[dev]"

cp .env.example .env          # set SECRET_KEY + BRIDGE_AUTH_TOKEN to long random strings

docker compose -f docker/docker-compose.yml up -d postgres redis
alembic upgrade head
```

Run the backend (separate terminals):
```bash
uvicorn platform.main:app --reload --port 8000
python -m platform.bridge.server --port 9000
celery -A platform.infrastructure.celery_app worker -l info
```

### Frontend (Next.js 16 + bun)

```bash
cd frontend
cp .env.example .env.local
bun install
bun run dev                   # http://localhost:3000
```

### Run tests

```bash
pytest                                       # all
pytest tests/unit/                           # fast, no services
pytest tests/unit/test_order_aggregate.py -v # one test
pytest --cov=platform --cov-report=html      # coverage → htmlcov/index.html
```

## Code Style

### Backend
- **Python 3.13+** — modern syntax: `match/case`, `type | None`, f-strings.
- **Type hints required** — mypy strict mode (Pydantic plugin).
- **Async-first** — every I/O function is `async def`.
- **Line length**: 100 (Ruff/Black). **Imports**: sorted by Ruff.
- **Docstrings** on every public class, function, and method.

### Frontend
- **TypeScript**, React 19, Tailwind v4, shadcn UI.
- **Biome** for lint + format (`bun run check`); Husky + lint-staged auto-fix on commit.
- Match the surrounding code's patterns (RHF + Zod for forms, TanStack-style tables, Recharts).

## Architecture Rules (Enforced in Review)

### Wine Discipline
No code in `src/platform/` may:
- `import wine`
- `import subprocess` with `wine` as target
- `import MetaTrader5`

All MT5 access goes through `platform.infrastructure.mt5_bridge.client.BridgeClient`.

### Clean Architecture
Dependencies always point inward:
- `domain/` — no imports from infrastructure or API.
- `application/` — may import domain + infrastructure interfaces.
- `infrastructure/` — may import domain + application.
- `api/` — may import application + infrastructure.

### Multi-Tenancy
Every database table that owns user data MUST carry `org_id`. Every query path MUST filter by
`org_id` from the `CurrentUser` dependency.

### Async
Every function that does I/O MUST be `async def`. The only exception is Celery task wrappers
(which call `asyncio.run()` internally).

## Testing

- **Unit** — `tests/unit/` — pytest + pytest-asyncio; `monkeypatch`, `respx` (HTTP), `fakeredis`
  (Redis). Coverage target: 80%.
- **Integration** — `tests/integration/` — real PostgreSQL + Redis, mocked Bridge.
- **E2E** — `tests/e2e/` — full stack; API + WebSocket assertions on real state.

Fixtures of note: `local_only_bus` (no Redis), `clean_registry`, `clean_risk_engine`.

## Adding Things

### A strategy
1. Create `src/platform/strategies/builtin/your_strategy.py`.
2. Subclass `Strategy`, decorate with `@strategy`.
3. Implement `async def on_bar(self, bar, ctx) -> Signal | None`.
4. Add a test in `tests/unit/`.
5. Document parameters in the class docstring.

```python
@strategy
class MyStrategy(Strategy):
    name = "my_strategy"
    version = "1.0.0"
    default_config = {"period": 14}

    def __init__(self, *, period: int = 14):
        self.period = period

    async def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal | None:
        ...
        return Signal(symbol=bar.symbol, side="buy", strength=0.8)
```

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
5. Add a test (**required** — CI blocks risk changes without tests).

### An execution adapter
1. Subclass `ExecutionAdapter` (`infrastructure/execution/adapter_base.py`).
2. Register at import time: `get_adapter_registry().register("your_kind", YourAdapter)`.
3. No core code changes — the application layer uses `ExecutionAdapter` uniformly.

### A REST router
Follow `src/platform/api/v1/{terminals,orders}.py`: `APIRouter(prefix=..., tags=...)`,
`get_current_user`/`require_role` deps, Pydantic `Out` models with `from_attributes`, org-scoped
queries. Register the router in `src/platform/main.py` `api_v1` list.

## Database Migrations

```bash
alembic revision --autogenerate -m "add your_column to terminals"   # create
alembic upgrade head                                                  # apply
alembic downgrade -1                                                  # rollback one
```

### Migration Rules (enforced by `pr-checks.yml`)
- Every migration MUST be backward-compatible (the previous version must still work).
- Never `DROP COLUMN` in the same release that stops using it — wait one release.
- If breaking, split into two migrations deployed across two releases.
- A migration without a paired test **fails CI**.

## Pull Request Process

1. Branch: `git checkout -b feature/your-feature`.
2. Write tests first (TDD encouraged).
3. Implement.
4. Run locally:
   ```bash
   ruff check src/ tests/ && ruff format --check src/ tests/
   mypy src/platform/
   pytest
   cd frontend && bun run check && bun run build
   ```
5. Squash commits: `git rebase -i main`.
6. Open a PR using the [template](.github/pull_request_template.md) — clear description, link
   the issue, screenshots if the UI changed.
7. CI must pass: lint, type-check, unit tests, security scan.
8. One approval required for merge.

CI also runs **PR safety checks** (`pr-checks.yml`): auto-label by path, PR size warning,
migration↔test pairing enforcement, risk-module test enforcement, and a dependency-change
summary comment.

## Release Process

Releases are automated by [semantic-release](https://python-semantic-release.readthedocs.io/)
(`release.yml`), driven by [Conventional Commits](https://www.conventionalcommits.org/):

- `fix:` → patch · `feat:` → minor · `feat!` / `BREAKING CHANGE` → major.

On release: bumps `pyproject.toml`, regenerates `CHANGELOG.md`, creates a GitHub Release, pushes
a `v<X.Y.Z>` tag → that tag triggers `cd.yml` → production deploy (with approval gate and
automatic rollback on health-check failure).

## Code Review Checklist

- [ ] Type hints on all functions
- [ ] Async for all I/O
- [ ] No `wine` / `subprocess` / `MetaTrader5` imports outside the bridge
- [ ] `org_id` filtering on all DB queries
- [ ] Tests added/updated
- [ ] No secrets in code or logs
- [ ] Docstrings on new public APIs
- [ ] Migration is backward-compatible (or split across two releases)
- [ ] Frontend: `bun run check` and `bun run build` pass
