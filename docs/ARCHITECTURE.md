# ATLAS — Architecture

This document describes the runtime topology, the layering, the MT5 Bridge indirection, the
event bus, the execution-adapter abstraction, multi-tenancy, and the data model.

> For the original design narrative, see [ATLAS-Architecture.pdf](ATLAS-Architecture.pdf).
> For endpoint details, see [API.md](API.md).

---

## 1. Process topology

ATLAS runs as several cooperating processes:

| Process | Entry point | Port | Owns |
|---|---|---|---|
| **REST API** | `platform.main:app` (`uvicorn platform.main:app`) | 8000 | Public REST + WebSocket endpoints, lifespan wiring |
| **Bridge Service** | `python -m platform.bridge.server` | 9000 | WebSocket server MT5 terminals dial into |
| **Celery worker** | `celery -A platform.infrastructure.celery_app worker` | — | Backtests, tick archival, notifications |
| **Celery beat** | `celery -A platform.infrastructure.celery_app beat` | — | Periodic tasks (sync, archive, health) |
| **Admin console** | `cd frontend && bun run dev` | 3000 | Next.js operator UI |

In production, nginx fronts the API, Bridge, and console:

```
       nginx (:80/:443)
  /      →  frontend (:3000)
  /api/  →  api (:8000)
  /ws/   →  api (:8000)        # ticks + terminal-events
  /bridge/ → bridge (:9000)    # MT5 terminals
```

### Why the Bridge is a separate process

The backend **never shells out to `wine` or `mt5.exe`**. Wine is treated as an OS dependency.
All communication with MT5 happens through the Bridge over a versioned JSON protocol carried by
WebSocket. This is the **Wine rule** — it keeps the OS/process boundary clean and makes MT5
replaceable. The Bridge is *stateless* except for the in-memory terminal registry (rebuilt from
`REGISTER` events on reconnect); for HA, run multiple Bridge nodes behind a sticky-session load
balancer (sharded by `terminal_id` hash).

---

## 2. Layering (DDD + CQRS)

Dependencies always point **inward**. The domain layer has no infrastructure imports.

```
api/  ──►  application/  ──►  domain/  ◄──  infrastructure/
            │                              │
            └──── uses repositories ───────┘
```

| Layer | Location | Role |
|---|---|---|
| **API** | `src/platform/api/v1/`, `api/ws/` | Public REST + WS entry, auth, validation, response shaping |
| **Application** | `src/platform/application/{commands,queries,handlers}` | CQRS use cases / transaction scripts — orchestrates domain + infra |
| **Domain** | `src/platform/domain/` | Pure business rules: Trading, Risk, Strategy, MarketData, AI, Identity. No I/O |
| **Infrastructure** | `src/platform/infrastructure/` | Adapters: PostgreSQL, Redis, Celery, mt5_bridge, execution adapters, repositories |

The canonical vertical slice is `application/commands/place_order.py`:

```
validate → risk.check_order → persist Order (PENDING) → bridge.place_order (BLOCKS for ack)
         → map reply → update Order row
```

Every other use case follows this shape.

---

## 3. The MT5 Bridge

### Protocol (`infrastructure/mt5_bridge/protocol.py`)

A single envelope, `BridgeMessage`, is used in both directions:

```jsonc
{ "v": 1, "t": "cmd.order.place", "id": "<uuid4>",
  "ts": "<ISO-8601>", "terminal_id": "mt5-exness-01",
  "reply_to": "<uuid4|null>", "payload": { ... } }
```

- **`v`** — protocol version (currently 1)
- **`t`** — message type — see `CommandType` (server→terminal) and `EventType` (terminal→server)
- **`id`** — correlation id for matching request ↔ response
- **`reply_to`** — on responses, echoes the original command id
- **`payload`** — typed dict (`PlaceOrderPayload`, `ExecutionReportPayload`, …)

The protocol is transport-agnostic. Today it's carried by WebSocket; it could become gRPC,
AMQP, or a FIX-like binary frame without changing the envelope.

### Components

- **`bridge/server.py`** — the WebSocket server (one `BridgeSession` per connection).
- **`bridge/handlers.py`** — dispatch table: `REGISTER`, `HEARTBEAT`, `TICK`, `ORDER_*`,
  `POSITION_*`, `ACCOUNT_UPDATE`, `ERROR`. Handlers are fast — they fan out to the event bus.
- **`TerminalRegistry`** (`infrastructure/mt5_bridge/registry.py`) — in-memory map of connected
  terminals + heartbeat watcher (marks `degraded` then `offline` then evicts).
- **`CommandQueue`** (`infrastructure/mt5_bridge/command_queue.py`) — tracks pending commands per
  terminal; each command holds an `asyncio.Future` resolved by the matching reply (or a timeout
  watchdog / `fail_all` on disconnect).
- **`BridgeClient`** (`infrastructure/mt5_bridge/client.py`) — the *only* thing the application
  layer calls to reach a terminal. Keeping the indirection in one place lets us swap WebSocket
  for another transport without touching use-case code.

### Connection lifecycle

1. EA attaches in MT5, dials `ws(s)://bridge/...` with `InpAuthToken == BRIDGE_AUTH_TOKEN`.
2. On connect, EA sends `evt.register` → `handle_register` validates the token, records the
   terminal in the registry, publishes `terminal_registered`.
3. EA streams `evt.heartbeat`, `evt.tick`, `evt.order.*`, `evt.position.*`, `evt.account.update`.
4. Server→terminal commands (`cmd.order.place`, `cmd.position.close`, `cmd.account.sync`, …)
   are sent on the session and awaited via the `CommandQueue`.
5. On disconnect, the registry evicts the terminal and `fail_all` rejects every pending command.

---

## 4. Execution adapters

The platform never assumes MT5 at the application layer. Every execution venue implements
`ExecutionAdapter` (`infrastructure/execution/adapter_base.py`):

```python
class ExecutionAdapter(abc.ABC):
    adapter_kind: str
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def place_order(self, req: OrderRequest) -> ExecutionReport: ...
    async def cancel_order(self, broker_order_id: str) -> ExecutionReport: ...
    async def close_position(self, broker_position_id, volume=None) -> ExecutionReport: ...
    async def modify_position(self, broker_position_id, *, stop_loss=None, take_profit=None) -> ExecutionReport: ...
    async def sync_positions(self) -> list[PositionSnapshot]: ...
    async def sync_account(self) -> AccountSnapshot: ...
    async def subscribe_ticks(self, symbols: list[str]) -> None: ...
    async def get_history(self, *, symbol, timeframe, start, end) -> list[dict]: ...
```

The `ExecutionAdapterRegistry` (`infrastructure/execution/registry.py`) is pre-populated with
two built-ins:

- **`"mt5"`** → `BridgeClientAdapter` — wraps the async `BridgeClient` and adapts its
  keyword-call API to the uniform `ExecutionAdapter` interface (binds to one `terminal_id`).
- **`"paper"`** → `PaperBrokerAdapter` — in-memory simulator for backtests, paper trading, CI.

Third-party adapters (e.g. a Binance FIX adapter) register at import time:

```python
from platform.infrastructure.execution import get_adapter_registry
get_adapter_registry().register("binance", BinanceAdapter)
```

---

## 5. Event bus

`events/bus.py` is **two-tier**:

1. **In-process** — `publish()` invokes registered async handlers synchronously in the same
   process. This is the hot path: ticks fan out to the market-data engine, strategies, and AI
   modules with sub-millisecond latency.
2. **Redis pubsub** — the same publish also fans out to other processes, which deliver to their
   own local subscribers. This is how the API process pushes ticks to browser WebSockets even
   though ticks arrive on the Bridge process.

```python
async def publish(self, topic: str, payload: dict) -> None:
    for h in self._handlers.get(topic, []):   # local (fast)
        await h(payload)
    if self._redis is not None and not self._local_only:
        await self._redis.publish(topic, body)  # cross-process
```

For at-least-once delivery with retries, subscribe Celery tasks
(`infrastructure/tasks.py` → `process_execution_report`, etc.). In tests the bus runs in
`local_only` mode (no Redis) via the `local_only_bus` fixture.

### Topics (`events/topics.py`)

`TICKS`, `TERMINAL_EVENTS`, `EXECUTION_REPORTS`, `POSITION_UPDATES`, `ACCOUNT_UPDATES`,
`RISK_EVENTS`, `ORDERS`, `AUDIT`.

### WebSocket endpoints

- **`/ws/ticks`** — client sends `{"symbols": ["EURUSD", ...]}` then receives ticks (or a 30s
  ping when idle). Backpressure: bounded `asyncio.Queue`, drops on overflow.
- **`/ws/terminal-events`** — fan-in of `TERMINAL_EVENTS` + `EXECUTION_REPORTS` + `RISK_EVENTS`.

Both authenticate via `?token=<jwt>` (WebSocket can't set headers).

---

## 6. Strategies, AI, Risk

### Strategies (`strategies/sdk`)

A strategy is a **pure function**: `(market_data, context) → Signal | None`. It has no DB
access, no HTTP, no side effects. The orchestrator invokes `on_bar` (closed bars) and/or
`on_tick` and feeds signals to the application layer.

```python
@strategy
class EMACross(Strategy):
    name = "ema_cross"
    default_config = {"fast": 9, "slow": 21}

    async def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal | None:
        ...
        return Signal(symbol=bar.symbol, side="buy", strength=0.7)
```

Built-ins: `ema_cross`, `rsi_reversion`, `breakout`, `grid`, `smc_order_blocks`,
`liquidity_sweep`, `macd_divergence`, `news_overlay`.

### AI modules (`ai/sdk`)

Each AI module is a specialized analyst:

```python
class AIModule(abc.ABC):
    name: str
    async def analyze(self, ctx: AIContext) -> AIPrediction: ...
```

Modules: `trend`, `volatility`, `pattern`, `sentiment`, `portfolio`, `position_size`,
`anomaly_detection`, `economic_calendar`, `trade_journal`, `trade_quality`,
`strategy_generator`, `llm_assistant`. The orchestrator fan-ins all module outputs into a
single `composite_score`. (Modules are currently heuristic; ONNX model loading is planned.)

### Risk engine (`risk/engine.py`)

Pluggable rule pack. **Every order passes through `check_order` before it leaves the system.**
If any rule raises `RiskLimitBreached`, the order never reaches the bridge.

```python
class RiskRule(abc.ABC):
    name: str
    async def evaluate(self, ctx: OrderContext) -> None: ...   # raise to reject
```

Rules: `max_exposure`, `position_limit`, `sector_exposure`, `spread_protection`,
`volatility_lock`, `correlation_risk`, `news_lock`, `kelly_sizing`, `max_daily_loss`,
`max_drawdown`. The **kill switch** (`risk/engine.py → KillSwitch`) blocks all new orders
globally when engaged.

---

## 7. Multi-tenancy & security

- Every table that owns user data carries `org_id`. Every query path filters by `org_id` from
  the `CurrentUser` dependency.
- Auth: **JWT** (`Authorization: Bearer <access>`) **or** **API key** (`X-API-Key`). JWTs are
  HS256 access (15 min) + refresh (30 d) pairs; API keys are hashed (bcrypt) at rest with a
  stored `key_prefix` for UI display and lookup.
- Roles: `admin`, `trader`, `viewer`, `bot`. `require_role(...)` gates admin endpoints.
- The console authenticates via a Next.js BFF (`/api/auth/*`) that sets **JS-readable cookies**
  so SSR middleware can guard routes and the WS client can append `?token=`. The backend
  re-validates the JWT on every request.
- Audit trail: every sensitive action writes to the append-only `audit_logs` table.

---

## 8. Data model

Initial schema in [`alembic/versions/0001_initial.py`](../alembic/versions/0001_initial.py).
UUID primary keys; `ticks`/`candles` use integer PKs for throughput. All multi-tenant.

```
organizations ─┬─ users ─ api_keys
               ├─ brokers ─ terminals ─ accounts
               │              ├─ orders ─ executions
               │              ├─ positions ─ trades
               │              └─ ticks / candles
               ├─ strategies ─ signals
               │             └─ backtests
               ├─ risk_events
               ├─ notifications
               ├─ ai_results
               └─ audit_logs
symbols (shared or broker-scoped)
```

Key conventions:

- `TimestampMixin` — `created_at`/`updated_at`; `SoftDeleteMixin` — `deleted_at`.
- `Numeric(20, 5)` for prices, `Numeric(20, 2)` for P&L, `Numeric(5, 4)` for confidence/strength.
- `ticks` is partitioned by month in production; swap for a TimescaleDB hypertable at scale
  (see roadmap).

---

## 9. Configuration & observability

- **Config** — `core/config.py` (Pydantic Settings, `.env`). Key vars: `SECRET_KEY`,
  `BRIDGE_AUTH_TOKEN`, `DATABASE_URL`, `REDIS_URL`, `LLM_PROVIDER`.
- **Logging** — structlog JSON to stdout.
- **Tracing** — OpenTelemetry (`otel_exporter_otlp_endpoint`).
- **Metrics** — Prometheus on `PROMETHEUS_METRICS_PORT` (9101): HTTP latency/requests, bridge
  command latency, terminals online, orders placed, risk decisions, DB pool.
- **Health** — `/health`, `/health/live`, `/health/ready`, `/health/detailed`.

---

## 10. Backtesting

`backtest/` runs an event-driven simulation out-of-process on a Celery worker. The HTTP request
never blocks on the simulation: `POST /backtests` inserts a `PENDING` row, enqueues
`platform.tasks.run_backtest`, and returns immediately; the caller polls `GET /backtests/{id}`.
`PaperBrokerAdapter` provides the simulated fills.
