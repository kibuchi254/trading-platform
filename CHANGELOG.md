# CHANGELOG

<!-- version list -->

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
