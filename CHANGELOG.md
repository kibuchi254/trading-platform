# CHANGELOG

<!-- version list -->

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
