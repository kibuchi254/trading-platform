# ATLAS — API Reference

All endpoints are under `/api/v1` (REST) or `/ws` (WebSocket). Interactive docs are available
at `http://localhost:8000/docs` (Swagger) and `/redoc` when the API is running.

## Authentication

Two mutually exclusive methods, resolved from the request headers:

| Method | Header | Notes |
|---|---|---|
| JWT | `Authorization: Bearer <access_token>` | Obtain via `POST /auth/login`; access TTL 15 min, refresh 30 d |
| API key | `X-API-Key: atlas_<random>` | Created via `POST /auth/api-keys`; shown once |

WebSocket endpoints can't set headers, so they take the JWT as a query param: `?token=<jwt>`.

### `POST /auth/login`
```jsonc
// request
{ "email": "you@example.com", "password": "********" }
// 200
{ "access_token": "...", "refresh_token": "...", "token_type": "Bearer", "expires_in": 900 }
```

### `POST /auth/register`
First-run bootstrap — creates an organization and its first admin.
```jsonc
// request
{ "org_name": "Acme Capital", "org_slug": "acme-capital",
  "email": "admin@acme.capital", "password": "********", "display_name": "Jane Trader" }
// 201 → token pair (same shape as /login)
```

### `POST /auth/refresh`
```jsonc
{ "refresh_token": "..." }   // → new token pair
```

### `POST /auth/api-keys?name=<name>`
Returns the raw key **once**; only the hash + `key_prefix` are persisted.
```jsonc
// 201
{ "id": "<uuid>", "name": "ci", "key_prefix": "atlas_a",
  "raw_key": "atlas_<...>", "scopes": ["admin"] }
```

### `GET /auth/me`
```jsonc
{ "user_id": "<uuid>", "org_id": "<uuid>", "email": "...",
  "display_name": "...", "role": "admin", "auth_method": "jwt" }
```

---

## Terminals

### `GET /terminals?status=<online|offline|degraded>`
```jsonc
[{ "id": "<uuid>", "terminal_id": "mt5-exness-01", "broker": null,
   "broker_account": "12345678", "adapter_kind": "mt5", "version": "5.0.0",
   "status": "online", "last_heartbeat_at": "2026-08-03T...", "symbols": ["EURUSD", ...],
   "capabilities": { ... }, "is_online": true }]
```

### `GET /terminals/{terminal_id}` — single terminal.

### `POST /terminals/{terminal_id}/sync-positions` → `{ "status": "ok", "received": "3" }`
### `POST /terminals/{terminal_id}/sync-account` → `{ "status": "ok", "account": { ... } }`
### `POST /terminals/{terminal_id}/flatten` — emergency button; closes all positions + cancels all orders.
```jsonc
{ "terminal_id": "mt5-exness-01", "positions_closed": 3, "orders_cancelled": 1, "flattened_at": "..." }
```

---

## Orders

### `POST /orders` — place order (blocks until the terminal acks)
```jsonc
// request
{ "terminal_id": "mt5-exness-01", "symbol": "EURUSD", "side": "buy",
  "order_type": "market",            // market | limit | stop | stop_limit
  "volume": 0.1, "price": null,      // required for non-market
  "stop_loss": 1.0850, "take_profit": 1.0950,
  "strategy_id": null, "comment": null, "magic": null }
// 201
{ "order_id": "<uuid>", "client_order_id": "atlas-...", "broker_order_id": "...",
  "status": "filled", "filled_volume": 0.1, "avg_fill_price": 1.0900, "rejection_reason": null }
```
### `GET /orders?status=<...>&limit=<100>` — blotter.
### `GET /orders/{order_id}`
### `POST /orders/{order_id}/cancel` — cancels a pending/submitted/partial order.

---

## Positions

### `GET /positions?status=<all|open|closed>&limit=<200>`
```jsonc
{ "positions": [{ "id": "<uuid>", "terminal_id": "<uuid>", "broker_position_id": "...",
  "symbol": "EURUSD", "side": "buy", "volume": 0.1, "open_price": 1.0900,
  "current_price": 1.0912, "stop_loss": null, "take_profit": null, "swap": 0,
  "unrealized_pnl": 12.0, "realized_pnl": 0, "status": "open",
  "opened_at": "...", "closed_at": null }], "total": 1 }
```
### `GET /positions/{position_id}`
### `POST /positions/{position_id}/close` — body `{ "volume": null }` (null = full close).
### `POST /positions/{position_id}/modify` — body `{ "stop_loss": 1.085, "take_profit": 1.095 }`.

---

## Trades (the ledger)

### `GET /trades?symbol=<>&strategy_id=<>&limit=<100>`
```jsonc
{ "trades": [{ "id": "<uuid>", "position_id": "<uuid>", "strategy_id": null,
  "symbol": "EURUSD", "side": "buy", "volume": 0.1, "entry_price": 1.0900,
  "exit_price": 1.0912, "pnl": 12.0, "pips": 12.0, "commission": 0, "swap": 0,
  "duration_seconds": 3600, "opened_at": "...", "closed_at": "..." }], "total": 1 }
```

---

## Signals

### `GET /signals?symbol=<>&strategy_id=<>&limit=<50>`
Most recent strategy / AI signals for the org.

---

## Strategies

### `GET /strategies` — org strategies.
### `GET /strategies/available` — SDK-registered strategy kinds + default configs.
### `POST /strategies` — `{ "name": "...", "slug": "...", "kind": "ema_cross", "config": {}, "description": "" }`
### `POST /strategies/{id}/activate` · `POST /strategies/{id}/deactivate`

---

## Backtests

### `GET /backtests?limit=<50>`
### `POST /backtests` — queues a simulation; returns immediately.
```jsonc
{ "strategy_id": "<uuid>", "symbol": "EURUSD", "timeframe": "M15",
  "start": "2026-01-01T00:00:00Z", "end": "2026-07-01T00:00:00Z",
  "initial_capital": 10000.0, "config": {} }
// 201
{ "backtest_id": "<uuid>", "status": "pending", "queued": true }
```
### `GET /backtests/{id}` — includes `final_equity`, `max_drawdown`, `sharpe`, `trades_count`, `results` (JSONB) once complete.

---

## Risk

### `GET /risk/kill-switch` → `{ "engaged": false }`
### `POST /risk/kill-switch/engage` — admin/trader. Blocks all new orders globally.
### `POST /risk/kill-switch/release` — admin only.
### `GET /risk-events?severity=<>&rule=<>&resolved=<>&limit=<50>`
```jsonc
{ "events": [{ "id": "<uuid>", "terminal_id": null, "rule": "max_daily_loss",
  "severity": "critical", "action": "block", "details": { ... }, "order_id": null,
  "resolved": false, "resolved_at": null, "created_at": "..." }] }
```

---

## AI

### `POST /ai/analyze`
```jsonc
{ "symbol": "EURUSD", "timeframe": "M15", "features": { "ema_fast": 1.09, "ema_slow": 1.08, "adx": 28 } }
// 200
{ "symbol": "EURUSD", "modules": { "trend": { "direction": "bullish", "confidence": 0.56, ... }, ... },
  "composite_score": 0.62 }
```
### `POST /ai/assistant/chat` — `{ "message": "...", "context": {} }` → `{ "reply": "..." }`.
Requires `LLM_PROVIDER != none`; otherwise returns a disabled stub.

---

## Analytics

### `GET /analytics/performance?days=<30>`
```jsonc
{ "total_trades": 42, "win_rate": 0.57, "total_pnl": 1234.56,
  "avg_pnl": 29.4, "best_trade": 210.0, "worst_trade": -80.0, "avg_duration_seconds": 3600 }
```
### `GET /analytics/positions/open` — list of open positions with uP&L.

---

## Market data

### `GET /market-data/symbols` — instrument catalog.
```jsonc
[{ "id": "<uuid>", "name": "EURUSD", "category": "fx", "digits": 5,
  "volume_min": 0.01, "volume_step": 0.01, "volume_max": 100 }]
```
### `GET /market-data/candles/{symbol}?timeframe=<M15>&limit=<500>` — OHLC bars (ascending).

---

## Brokers

### `GET /brokers` · `POST /brokers` (`{ "name", "code", "adapter_kind": "mt5", "credentials": {} }`) · `PATCH /brokers/{id}/deactivate`

---

## Notifications

### `GET /notifications?channel=<>&status=<>&mine=<bool>&limit=<100>` — in-app + sent-notification feed.

---

## Admin

> All `/admin/*` endpoints require the `admin` role.

### `GET /admin/status`
```jsonc
{ "terminals_online": 2, "pending_commands": 0, "risk_kill_switch": false, "env": "production" }
```
### `GET /admin/users` · `POST /admin/users` · `PATCH /admin/users/{id}/{activate,deactivate}`
### `GET /admin/audit-logs?action=<>&limit=<100>`

---

## WebSocket

Both require `?token=<jwt>`.

### `/ws/ticks`
1. Connect: `GET /ws/ticks?token=<jwt>`
2. Send a subscription: `{"symbols": ["EURUSD", "XAUUSD"]}` (empty = all)
3. Receive ticks:
```jsonc
{ "type": "tick", "terminal_id": "mt5-exness-01", "symbol": "EURUSD",
  "bid": 1.0900, "ask": 1.0901, "last": 1.0900, "volume": 0, "ts": "2026-08-03T..." }
```
A `{"type":"ping"}` is sent every 30s of idle. Backpressure: a bounded queue drops on overflow.

### `/ws/terminal-events`
Fan-in of `terminal_registered` / `terminal_flattened`, execution reports
(`order_accepted`, `order_filled`, …), and risk events. No subscription message required.

---

## Errors

Platform errors are returned as:
```jsonc
{ "code": "platform.risk.breach", "message": "Max exposure exceeded" }
```
HTTP status comes from the exception (`http_status`):

| Code | Status | Meaning |
|---|---|---|
| `platform.validation` | 422 | Invalid input |
| `platform.not_found` | 404 | Resource not found in the caller's org |
| `platform.conflict` | 409 | Duplicate / state conflict |
| `platform.auth` | 401 | Bad/expired token or API key |
| `platform.forbidden` | 403 | Insufficient role |
| `platform.rate_limit` | 429 | Rate limited |
| `platform.risk.breach` | 400 | A risk rule rejected the order |
| `platform.bridge.terminal_offline` | 502 | Terminal not connected |
| `platform.bridge.command_timeout` | 504 | Terminal didn't ack in time |
| `platform.infrastructure` | 503 | Dependency unavailable |
