"""Extended Prometheus metrics for the ATLAS platform.

This module complements :mod:`platform.core.telemetry` (which holds the
HTTP / bridge / risk / order counters) with metrics that track the higher-
level platform workflow:

* strategy activation / deactivation
* AI module predictions (per module + direction)
* tick ingestion (per terminal + symbol)
* tick DB persistence throughput
* event-bus publish / handle throughput (per topic)
* open positions (per org + terminal)
* DB connection-pool utilisation

It also exposes :func:`instrument_event_bus`, which monkey-patches the
:class:`~platform.events.bus.EventBus` instance so that every
``publish`` and every subscriber invocation automatically emits the
appropriate counter. This keeps metrics concerns out of the bus itself.

All metrics use the ``atlas_`` prefix to avoid collisions when scraped
into a shared Prometheus instance.
"""

from __future__ import annotations

from platform.core.logging import get_logger
from typing import TYPE_CHECKING, Any

from prometheus_client import Counter, Gauge

if TYPE_CHECKING:
    from platform.events.bus import EventBus

_log = get_logger(__name__)


# ── Metric definitions ────────────────────────────────────────────────

STRATEGIES_ACTIVE = Gauge(
    "atlas_strategies_active",
    "Number of active strategies currently running",
    ["org_id"],
)

AI_PREDICTIONS = Counter(
    "atlas_ai_predictions_total",
    "AI module predictions emitted, partitioned by module and direction",
    ["module", "direction"],
)

TICKS_RECEIVED = Counter(
    "atlas_ticks_received_total",
    "Ticks received from the MT5 bridge, partitioned by terminal and symbol",
    ["terminal_id", "symbol"],
)

TICKS_PERSISTED = Counter(
    "atlas_ticks_persisted_total",
    "Ticks successfully persisted to the database",
)

EVENT_BUS_PUBLISHED = Counter(
    "atlas_event_bus_published_total",
    "Events published to the event bus, partitioned by topic",
    ["topic"],
)

EVENT_BUS_HANDLED = Counter(
    "atlas_event_bus_handled_total",
    "Events successfully handled by subscribers, partitioned by topic",
    ["topic"],
)

POSITIONS_OPEN = Gauge(
    "atlas_positions_open",
    "Number of open positions, partitioned by org and terminal",
    ["org_id", "terminal_id"],
)

DB_POOL_IN_USE = Gauge(
    "atlas_db_pool_in_use",
    "Number of database connections currently checked out from the pool",
)


# ── Convenience helpers ───────────────────────────────────────────────


def record_tick(terminal_id: str, symbol: str) -> None:
    """Increment the tick-received counter for a (terminal, symbol) pair."""
    TICKS_RECEIVED.labels(terminal_id=terminal_id, symbol=symbol).inc()


def record_tick_persisted() -> None:
    """Increment the tick-persisted counter."""
    TICKS_PERSISTED.inc()


def record_ai_prediction(module: str, direction: str) -> None:
    """Increment the AI-prediction counter for a (module, direction) pair."""
    AI_PREDICTIONS.labels(module=module, direction=direction).inc()


def record_event_published(topic: str) -> None:
    """Increment the event-bus published counter for a topic."""
    EVENT_BUS_PUBLISHED.labels(topic=topic).inc()


def record_event_handled(topic: str) -> None:
    """Increment the event-bus handled counter for a topic."""
    EVENT_BUS_HANDLED.labels(topic=topic).inc()


def set_strategies_active(org_id: str, count: int) -> None:
    """Set the active-strategy gauge for an organisation."""
    STRATEGIES_ACTIVE.labels(org_id=org_id).set(count)


def inc_strategies_active(org_id: str) -> None:
    """Increment the active-strategy gauge for an organisation."""
    STRATEGIES_ACTIVE.labels(org_id=org_id).inc()


def dec_strategies_active(org_id: str) -> None:
    """Decrement the active-strategy gauge for an organisation."""
    STRATEGIES_ACTIVE.labels(org_id=org_id).dec()


def set_positions_open(org_id: str, terminal_id: str, count: int) -> None:
    """Set the open-positions gauge for an (org, terminal) pair."""
    POSITIONS_OPEN.labels(org_id=org_id, terminal_id=terminal_id).set(count)


def inc_positions_open(org_id: str, terminal_id: str) -> None:
    """Increment the open-positions gauge for an (org, terminal) pair."""
    POSITIONS_OPEN.labels(org_id=org_id, terminal_id=terminal_id).inc()


def dec_positions_open(org_id: str, terminal_id: str) -> None:
    """Decrement the open-positions gauge for an (org, terminal) pair."""
    POSITIONS_OPEN.labels(org_id=org_id, terminal_id=terminal_id).dec()


def set_db_pool_in_use(count: int) -> None:
    """Set the DB pool-in-use gauge."""
    DB_POOL_IN_USE.set(count)


def update_db_pool_in_use() -> None:
    """Refresh the DB pool-in-use gauge from the live engine.

    Reads the underlying async engine's sync-pool ``checkedout`` counter.
    Safe to call from a periodic task — never raises.
    """
    try:
        from platform.db.session import get_engine

        engine = get_engine()
        pool = engine.pool  # type: ignore[attr-defined]
        # AsyncAdaptedQueuePool exposes the sync pool's `checkedout()`.
        checkedout = pool.checkedout() if hasattr(pool, "checkedout") else 0
        DB_POOL_IN_USE.set(int(checkedout))
    except Exception:
        _log.debug("db_pool_gauge_update_failed")


# ── EventBus instrumentation ──────────────────────────────────────────


def instrument_event_bus(bus: EventBus) -> None:
    """Wrap an :class:`EventBus` so every publish/handle emits metrics.

    Wraps both :meth:`EventBus.publish` (counts every published event by
    topic) and :meth:`EventBus.subscribe` (wraps every registered handler
    so that successful invocations are counted by topic).

    The wrapping is idempotent: re-applying it on an already-instrumented
    bus is a no-op (guarded by the ``_atlas_instrumented`` attribute).
    """
    if getattr(bus, "_atlas_instrumented", False):
        _log.debug("event_bus_already_instrumented")
        return

    original_publish = bus.publish
    original_subscribe = bus.subscribe

    async def instrumented_publish(topic: str, payload: dict[str, Any]) -> None:
        EVENT_BUS_PUBLISHED.labels(topic=topic).inc()
        await original_publish(topic, payload)

    def instrumented_subscribe(topic: str, handler: Any) -> None:
        async def wrapped(payload: dict[str, Any]) -> None:
            try:
                await handler(payload)
                EVENT_BUS_HANDLED.labels(topic=topic).inc()
            except Exception:
                # The original bus already logs handler errors — we only
                # care about counting successful invocations, so re-raise.
                raise

        return original_subscribe(topic, wrapped)

    bus.publish = instrumented_publish  # type: ignore[method-assign]
    bus.subscribe = instrumented_subscribe  # type: ignore[method-assign]
    bus._atlas_instrumented = True
    _log.info("event_bus_instrumented")
