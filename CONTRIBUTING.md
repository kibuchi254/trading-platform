# ATLAS — Contributing Guide

## Development Setup

```bash
# Clone
git clone <repo-url>
cd trading-platform

# Install
uv venv --python 3.13
uv pip install -e ".[dev]"

# Pre-commit hooks
pre-commit install

# Start infra
docker compose -f docker/docker-compose.yml up -d postgres redis

# Migrate
alembic upgrade head

# Run tests
pytest tests/ -v

# Run specific test
pytest tests/unit/test_order_aggregate.py -v
```

## Code Style

- **Python 3.13+** — use modern syntax: `match/case`, `type | None`, f-strings
- **Type hints required** — mypy strict mode
- **Async-first** — every I/O function is `async def`
- **Line length**: 100 chars (enforced by Black + Ruff)
- **Imports**: sorted by Ruff (isort-compatible)
- **Docstrings**: every public class, function, and method

### Pre-commit Hooks

The repo includes `.pre-commit-config.yaml`:
- ruff check
- black
- mypy
- end-of-file-fixer
- trailing-whitespace

## Architecture Rules (Enforced)

### Wine Discipline
No code in `platform/` may:
- `import wine`
- `import subprocess` with `wine` as target
- `import MetaTrader5`

All MT5 access goes through `platform.infrastructure.mt5_bridge.client.BridgeClient`.

### Clean Architecture
Dependencies always point inward:
- `domain` — no imports from infrastructure or API
- `application` — may import domain + infrastructure interfaces
- `infrastructure` — may import domain + application
- `api` — may import application + infrastructure

### Multi-Tenancy
Every database table that owns user data MUST carry `org_id`. Every query path MUST filter by `org_id` from the `CurrentUser` dependency.

### Async
Every function that does I/O MUST be `async def`. The only exception is Celery task wrappers (which call `asyncio.run()` internally).

## Testing

### Unit Tests
- Location: `tests/unit/`
- Framework: pytest + pytest-asyncio
- Mocking: `monkeypatch`, `respx` for HTTP, `fakeredis` for Redis
- Coverage target: 80%

### Integration Tests
- Location: `tests/integration/`
- Requires: PostgreSQL + Redis running
- Pattern: real DB + real Redis, mocked Bridge

### End-to-End Tests
- Location: `tests/e2e/`
- Requires: full stack running
- Pattern: API calls + WebSocket connections + assertions on real state

### Running Tests

```bash
# All tests
pytest

# Unit only (fast, no services needed)
pytest tests/unit/

# Integration (needs PG + Redis)
pytest tests/integration/

# With coverage
pytest --cov=platform --cov-report=html
open htmlcov/index.html

# Specific test
pytest tests/unit/test_order_aggregate.py::test_order_starts_pending -v
```

## Adding a New Strategy

1. Create `src/platform/strategies/builtin/your_strategy.py`
2. Subclass `Strategy`, decorate with `@strategy`
3. Implement `async def on_bar(self, bar, ctx) -> Signal | None`
4. Add a test in `tests/unit/test_your_strategy.py`
5. Document parameters in the class docstring

Example:
```python
@strategy
class MyStrategy(Strategy):
    name = "my_strategy"
    version = "1.0.0"
    default_config = {"period": 14}

    def __init__(self, *, period: int = 14):
        self.period = period

    async def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal | None:
        # your logic
        return Signal(symbol=bar.symbol, side="buy", strength=0.8)
```

## Adding a New AI Module

1. Create `src/platform/ai/modules/your_module.py`
2. Subclass `AIModule`, implement `async def analyze(self, ctx) -> AIPrediction`
3. Register with the orchestrator in `platform/main.py` lifespan
4. Add a test

## Adding a New Risk Rule

1. Create `src/platform/risk/rules/your_rule.py`
2. Subclass `RiskRule`, implement `async def evaluate(self, ctx) -> None`
3. Raise `RiskLimitBreached` to reject
4. Register in `platform/risk/rules/__init__.py` via `register_all_rules()`
5. Add a test

## Database Migrations

```bash
# Create a new migration
alembic revision --autogenerate -m "add your_column to terminals"

# Review the generated file in alembic/versions/

# Apply
alembic upgrade head

# Rollback one
alembic downgrade -1
```

### Migration Rules
- Every migration MUST be backward-compatible (the previous version must still work)
- If a migration is breaking, split it into two migrations deployed across two releases
- Never `DROP COLUMN` in the same release that stops using it — wait one release

## Pull Request Process

1. Create a feature branch: `git checkout -b feature/your-feature`
2. Write tests first (TDD encouraged)
3. Implement
4. Run `pytest`, `ruff check`, `black --check`, `mypy`
5. Squash commits: `git rebase -i main`
6. Open PR with:
   - Clear description of what changed and why
   - Link to issue if applicable
   - Screenshots if UI changes (N/A for backend)
7. CI must pass: lint, typecheck, unit tests, security scan
8. One approval required for merge

## Release Process

1. Update version in `pyproject.toml`
2. Update `CHANGELOG.md`
3. Tag: `git tag v0.2.0`
4. Push tag: `git push origin v0.2.0`
5. CI builds and publishes Docker image
6. Manual approval for production deploy

## Code Review Checklist

- [ ] Type hints on all functions
- [ ] Async for all I/O
- [ ] No `wine` / `subprocess` / `MetaTrader5` imports outside bridge
- [ ] `org_id` filtering on all DB queries
- [ ] Tests added/updated
- [ ] No secrets in code or logs
- [ ] Docstrings on new public APIs
- [ ] Migration is backward-compatible
