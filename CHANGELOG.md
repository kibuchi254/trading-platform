# CHANGELOG

<!-- version list -->

## v1.0.14 (2026-07-10)

### Bug Fixes

- **deploy**: Stable project name, remove-orphans, fix worker healthcheck
  ([`949e484`](https://github.com/kibuchi254/trading-platform/commit/949e48419742c6fa9c7d88cb06e7852a63f6cfe3))


## v1.0.13 (2026-07-10)

### Bug Fixes

- Re-encode .gitignore as UTF-8 (was UTF-16, broke hatchling build)
  ([`3bf007f`](https://github.com/kibuchi254/trading-platform/commit/3bf007f1acad58d6073a61398b157c731185e03f))

### Chores

- Ignore __pycache__ and compiled Python files
  ([`73dd286`](https://github.com/kibuchi254/trading-platform/commit/73dd286f7ea7fa8ca5d206cc5c8f8073a121ca37))


## v1.0.12 (2026-07-10)

### Bug Fixes

- Change app metrics port from 9090 to 9101
  ([`c7b268f`](https://github.com/kibuchi254/trading-platform/commit/c7b268fece7e1e13787931e86c0f4956b7e1c787))


## v1.0.11 (2026-07-10)

### Bug Fixes

- **compose**: Restore missing redis service key dropped in previous edit
  ([`9d7fdde`](https://github.com/kibuchi254/trading-platform/commit/9d7fdde1932b46ce5faae09599e37dc121648cad))

### Code Style

- Ruff format bus.py
  ([`2bbc09f`](https://github.com/kibuchi254/trading-platform/commit/2bbc09fedca1cc98cc27ae537e122463435e021a))


## v1.0.10 (2026-07-10)

### Bug Fixes

- **redis**: Prevent crash-loop when REDIS_PASSWORD is empty
  ([`1ba4886`](https://github.com/kibuchi254/trading-platform/commit/1ba48866039d66d7198bbe1820e6bbccd5e64432))


## v1.0.9 (2026-07-10)

### Bug Fixes

- **bus**: Retry Redis ping on startup with exponential backoff
  ([`5050d94`](https://github.com/kibuchi254/trading-platform/commit/5050d94c41ee97aa50d78644ce2ce6c725dc7198))


## v1.0.8 (2026-07-10)

### Bug Fixes

- Resolve Redis DNS failure and Prometheus port collision on startup
  ([`aeb62f3`](https://github.com/kibuchi254/trading-platform/commit/aeb62f39ebe2beb0ed13ac6e517c91778cf9083c))


## v1.0.7 (2026-07-09)

### Bug Fixes

- Ignore Address already in use error in start_metrics_server for multi-worker support
  ([`2f0ef95`](https://github.com/kibuchi254/trading-platform/commit/2f0ef953f772e24585f3ccacdbdc7932667d81a8))


## v1.0.6 (2026-07-09)

### Bug Fixes

- Import TICKS_PERSISTED in metrics.py from telemetry.py to resolve duplicated timeseries
  registration
  ([`cc35421`](https://github.com/kibuchi254/trading-platform/commit/cc354215d9866a0493a353680caa77ce193cca95))


## v1.0.5 (2026-07-09)

### Bug Fixes

- Proxy standard library platform module in platform/__init__.py to prevent package shadowing errors
  ([`46140ab`](https://github.com/kibuchi254/trading-platform/commit/46140ab387c2ae5aed985c2530030fe3e21b1290))

### Chores

- Retrigger CI/CD deployment
  ([`3259508`](https://github.com/kibuchi254/trading-platform/commit/32595085edf3bd7cf54c258da247d73990aee488))


## v1.0.4 (2026-07-09)

### Bug Fixes

- Add PYTHONPATH to backend.Dockerfile to enable platform package discovery
  ([`f835132`](https://github.com/kibuchi254/trading-platform/commit/f835132867fa62061e8c495fa40f11c8ec10764d))


## v1.0.3 (2026-07-09)

### Bug Fixes

- Update relative path of env_file to '../../.env' in docker-compose.prod.yml
  ([`104dd5c`](https://github.com/kibuchi254/trading-platform/commit/104dd5c5e99cc2ea0a63a158b2fbc0aba3ef4dfc))


## v1.0.2 (2026-07-09)

### Bug Fixes

- Explicitly specify --env-file in docker compose commands in cd.yml to prevent interpolation
  failure
  ([`96ae6bc`](https://github.com/kibuchi254/trading-platform/commit/96ae6bcecf559c60c8c71930a6557e8c081623c4))

### Chores

- Trigger production deploy after environment configuration
  ([`379645c`](https://github.com/kibuchi254/trading-platform/commit/379645c830c5e817fbb6930ecb16674427df4889))


## v1.0.1 (2026-07-09)

### Bug Fixes

- Make production deployment steps conditional on SSH_HOST secret existence
  ([`2cd704d`](https://github.com/kibuchi254/trading-platform/commit/2cd704d50f0304258039f11f6bea63f8d276314b))


## v1.0.0 (2026-07-09)

- Initial Release
