# CHANGELOG

<!-- version list -->

## v1.12.2 (2026-08-04)

### Bug Fixes

- Persist MT5 terminals to PostgreSQL on registration
  ([`2eab6b5`](https://github.com/kibuchi254/trading-platform/commit/2eab6b50a1b02615d06d327d1276c96ba35faeff))


## v1.12.1 (2026-08-04)

### Bug Fixes

- **bridge-http**: Persist/stream account state + ticks + command delivery
  ([#134](https://github.com/kibuchi254/trading-platform/pull/134),
  [`2da58b1`](https://github.com/kibuchi254/trading-platform/commit/2da58b1f58f77d5a15425b3dda795b1405b925bb))


## v1.12.0 (2026-08-04)

### Features

- **dashboard**: Neomorphic theme preset + live MT5 account/data wiring
  ([#133](https://github.com/kibuchi254/trading-platform/pull/133),
  [`955fc78`](https://github.com/kibuchi254/trading-platform/commit/955fc78b85a7f660d42b2287668cbfb757eb992c))

### Testing

- **signals**: Fix loop-scope + formatting on schema test
  ([#133](https://github.com/kibuchi254/trading-platform/pull/133),
  [`955fc78`](https://github.com/kibuchi254/trading-platform/commit/955fc78b85a7f660d42b2287668cbfb757eb992c))

- **signals**: Regression test for signals.status schema column
  ([#133](https://github.com/kibuchi254/trading-platform/pull/133),
  [`955fc78`](https://github.com/kibuchi254/trading-platform/commit/955fc78b85a7f660d42b2287668cbfb757eb992c))


## v1.11.0 (2026-08-04)

### Features

- **terminals**: Merge live online registry records into list_terminals REST endpoint
  ([`0c0e5ec`](https://github.com/kibuchi254/trading-platform/commit/0c0e5ec77ceb47d517ba7293866391c30676c23a))


## v1.10.2 (2026-08-04)

### Bug Fixes

- **api**: Instantiate TerminalRecord with HttpSession in bridge_http register endpoint
  ([`1ec9fff`](https://github.com/kibuchi254/trading-platform/commit/1ec9fffcf4e943dbf92f447fcd512222fd32d508))


## v1.10.1 (2026-08-04)

### Bug Fixes

- **api**: Mount bridge_http router in FastAPI app factory
  ([`cece875`](https://github.com/kibuchi254/trading-platform/commit/cece875d3beec918db8cca664f4e48b65f772d94))

### Code Style

- **lint**: Fix ruff import sorting and type annotations in bridge_http.py
  ([`50a3e97`](https://github.com/kibuchi254/trading-platform/commit/50a3e97d7e740b356e835a0c92ae0ac49056b270))


## v1.10.0 (2026-08-04)

### Features

- **mt5**: Implement Zero-DLL native MQL5 WebRequest Expert Advisor and HTTP bridge endpoint
  ([`53c7d19`](https://github.com/kibuchi254/trading-platform/commit/53c7d197738d26e4a93df77d486eb1a031503fe5))


## v1.9.1 (2026-08-04)

### Bug Fixes

- **mql5**: Resolve sign mismatch and TERMINAL_BUILD compilation errors in BridgeEA.mq5
  ([`2927828`](https://github.com/kibuchi254/trading-platform/commit/292782867e796ca37a783ead577f28861be022f2))


## v1.9.0 (2026-08-04)

### Features

- **terminals**: Add 1-click Windows Auto-Installer (.bat) generator
  ([`c0d4924`](https://github.com/kibuchi254/trading-platform/commit/c0d4924fd68d531538d43b4d09dcfda444d4e1aa))


## v1.8.1 (2026-08-03)

### Bug Fixes

- **terminals**: Make Connect Terminal modal responsive with max-height scroll and full BridgeEA.mq5
  event handlers
  ([`0d30f8c`](https://github.com/kibuchi254/trading-platform/commit/0d30f8c2b40c4162b8a42d37b0e9a55837fe1855))


## v1.8.0 (2026-08-03)

### Features

- **terminals**: Add Download atlas_bridge.dll button and API route
  ([`61d7f74`](https://github.com/kibuchi254/trading-platform/commit/61d7f74dc51935f36086e31fea55c24db43666de))


## v1.7.0 (2026-08-03)

### Features

- **terminals**: Add wss://backend.vorte.dev/bridge/ host default and 1-click copy buttons for all 5
  MT5 parameters
  ([`e6ff9ca`](https://github.com/kibuchi254/trading-platform/commit/e6ff9caf46ad051695a6df075dbf301ba5bd8cc2))


## v1.6.0 (2026-08-03)

### Features

- **terminals**: Add tenant MT5 onboarding guide and BridgeEA download API route
  ([`08c49ff`](https://github.com/kibuchi254/trading-platform/commit/08c49ff22b3b10e5bf2f63ba2acef1700e796c74))


## v1.5.4 (2026-08-03)

### Bug Fixes

- **deploy**: Fix frontend healthcheck (hits a 200 page, not the redirecting /)
  ([`50284b0`](https://github.com/kibuchi254/trading-platform/commit/50284b067dd14a7cef086d23f7f9a8a0772efbec))


## v1.5.3 (2026-08-03)

### Bug Fixes

- **console**: Default API/WS base URL to same-origin, not localhost:8000
  ([`3cc4bb0`](https://github.com/kibuchi254/trading-platform/commit/3cc4bb042c0d5039094d98474411f03ea3c34368))


## v1.5.2 (2026-08-03)

### Bug Fixes

- **api**: Require auth on GET /strategies/available
  ([`a11ee0d`](https://github.com/kibuchi254/trading-platform/commit/a11ee0d2c4df07591654cc63fe18f78b4e8e63fa))

### Testing

- Add HTTP smoke tests for all console REST routes
  ([`ee5ae94`](https://github.com/kibuchi254/trading-platform/commit/ee5ae944b0336156ce9a57299f668cb044718ca2))


## v1.5.1 (2026-08-03)

### Bug Fixes

- **nginx**: Route /docs /redoc /openapi.json to the API
  ([`3d718fb`](https://github.com/kibuchi254/trading-platform/commit/3d718fb09e005b51e56f6c31fd12c8254e8b1783))


## v1.5.0 (2026-08-03)

### Documentation

- Rewrite README and add architecture/API/dev/security suite
  ([`bf1053b`](https://github.com/kibuchi254/trading-platform/commit/bf1053b1adaccb8bf680479bcc6fe6012825c146))

### Features

- **api**: Add management REST routers for the admin console
  ([`4bfcc5a`](https://github.com/kibuchi254/trading-platform/commit/4bfcc5a60c599d65c3bbefc8e53e1496caf576a5))

- **deploy**: Wire frontend service into compose and nginx routing
  ([`de0c698`](https://github.com/kibuchi254/trading-platform/commit/de0c698ebfc85513a14f8820aadfa274bd5bb1f1))


## v1.4.3 (2026-08-03)

### Bug Fixes

- **deploy**: Change grafana host port from 3000 to 3002 to avoid port collision
  ([`8b4159e`](https://github.com/kibuchi254/trading-platform/commit/8b4159ecfc7fe4a586a8c8a548c6f4ae8ebf2bf7))


## v1.4.2 (2026-08-03)

### Bug Fixes

- **auth**: Fix API_URL fallback in BFF routes from ?? to ||
  ([`c7a8a4b`](https://github.com/kibuchi254/trading-platform/commit/c7a8a4b102d04b0c2434e732c8555610aff979b0))


## v1.4.1 (2026-08-03)

### Bug Fixes

- Correct prometheus.yml volume mount path relative to compose file
  ([`398f2e9`](https://github.com/kibuchi254/trading-platform/commit/398f2e9c0e1264c46e446d6505f392dc36570f94))


## v1.4.0 (2026-08-03)

### Features

- Add frontend source and Dockerfile for CI builds
  ([`be9b020`](https://github.com/kibuchi254/trading-platform/commit/be9b020c516664003b9cbe0c51b00ffc2dc41cdc))


## v1.3.0 (2026-08-03)

### Features

- Unified CI/CD pipeline — build and deploy frontend alongside backend
  ([`11a1ebb`](https://github.com/kibuchi254/trading-platform/commit/11a1ebbf43f33c8bde24b778d0dd17d7e1b2300a))


## v1.2.0 (2026-07-10)


## v1.1.1 (2026-07-10)


## v1.1.0 (2026-07-10)

### Features

- **mql5**: Add native C++ WinHTTP websocket DLL source and README
  ([`17103d3`](https://github.com/kibuchi254/trading-platform/commit/17103d3e3e1bb8d56cb832da222b3e115a1ce592))


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
