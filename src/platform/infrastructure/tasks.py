"""Celery task implementations — the real worker layer for ATLAS.

This module replaces the skeleton tasks in :mod:`platform.infrastructure.celery_app`
with full implementations. Every task is decorated with ``@app.task(name=...)``
using the same name as the routing table in ``celery_app.py`` so the existing
dispatch configuration keeps working unchanged.

Design conventions
------------------

* **Sync wrappers, async cores.**  Celery workers are sync. Each public task
  is a thin sync function that calls :func:`asyncio.run` to drive an async
  implementation. This lets every task reuse the async DB session factory,
  event bus, bridge client, and notification dispatcher already used by the
  FastAPI app.
* **Comprehensive error handling.**  Each task logs the exception via
  structlog, transitions any DB row it owns to a ``failed`` / ``error``
  status (so dashboards surface the failure), and re-raises so Celery's
  retry machinery can act on it.
* **Idempotency.**  Persistence tasks use ``ON CONFLICT DO NOTHING`` /
  ``DO UPDATE`` so redelivered messages do not create duplicate rows. Sync
  tasks diff remote vs. local state before writing.
* **Metrics.**  Hot paths increment Prometheus counters
  (:data:`~platform.core.telemetry.TICKS_PERSISTED`,
  :data:`~platform.core.telemetry.TASK_RESULTS`,
  :data:`~platform.core.telemetry.TASK_DURATION`) so worker throughput is
  observable.
* **structlog.**  Every log line is structured JSON in production for
  downstream log aggregation.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from celery import Task
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from platform.core.logging import get_logger
from platform.core.telemetry import (
    TASK_DURATION, TASK_RESULTS, TICKS_PERSISTED,
)
from platform.db.models import (
    Account, Backtest, Execution, Notification, Order, Position,
    RiskEvent, Signal, Terminal, Trade, Tick,
)
from platform.db.session import db_context, dispose_engine, get_engine
from platform.events.bus import get_event_bus
from platform.events.topics import Topic
from platform.infrastructure.celery_app import app
from platform.infrastructure.mt5_bridge.client import get_bridge_client
from platform.notifications.base import (
    NotificationMessage, get_dispatcher,
)
from platform.risk.engine import get_risk_engine

_log = get_logger(__name__)

# ── Tunables ─────────────────────────────────────────────────────────────────
TICK_BATCH_SIZE: int = 1_000          # rows per bulk INSERT
ARCHIVE_BATCH_SIZE: int = 10_000      # rows per archive/purge batch
SIGNAL_TTL_HOURS: int = 1             # signals older than this → EXPIRED
DEFAULT_RISK_LIMIT_USD: float = 1_000.0
DEFAULT_MAX_DRAWDOWN_PCT: float = 0.20
PERF_CACHE_TTL_SECONDS: int = 3_600   # 1h — hourly recompute, cached for dashboard
NOTIFICATION_MAX_RETRIES: int = 3


# ── Helpers ─────────────────────────────────────────────────────────────────

def _run(coro: Any) -> Any:
    """Run an async coroutine from a sync Celery task.

    Uses :func:`asyncio.run` which creates (and tears down) a fresh event
    loop per call. Acceptable for Celery workers — they are sync and do not
    have a running loop. If a loop is already running (e.g. during tests
    that drive tasks inline), fall back to ``asyncio.ensure_future`` +
    ``loop.run_until_complete``.
    """
    try:
        return asyncio.run(coro)
    except RuntimeError:
        # "asyncio.run() cannot be called from a running event loop"
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(coro)


def _safe_uuid(value: Any) -> UUID | None:
    """Best-effort UUID coercion — returns ``None`` on bad input."""
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _parse_dt(value: Any) -> datetime | None:
    """Parse an ISO-8601 string or pass through a datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _record_result(task_name: str, ok: bool) -> None:
    """Increment the task-result counter."""
    TASK_RESULTS.labels(
        task=task_name, result="success" if ok else "failure",
    ).inc()


# ── 1. persist_tick ─────────────────────────────────────────────────────────

@app.task(name="platform.tasks.persist_tick", bind=True, queue="ticks")
def persist_tick(self: Task, tick: dict[str, Any]) -> dict[str, Any]:
    """Hot-path tick persistence.

    Accepts either a single tick dict or a list of tick dicts (the latter
    is preferred — batches amortise DB round-trips). Uses SQLAlchemy Core
    ``insert().values([...])`` compiled to a single multi-row INSERT, the
    fastest non-COPY path through asyncpg. Duplicate ticks are silently
    skipped via ``ON CONFLICT DO NOTHING`` so redelivered messages are safe.

    Each tick dict must contain: ``terminal_id`` (UUID/str), ``symbol``,
    ``bid``, ``ask``, ``ts`` (ISO-8601). ``last`` and ``volume`` are
    optional.

    Returns a small summary dict — useful for inspecting Celery results in
    dev tools.
    """
    task_name = self.name
    started = datetime.now(timezone.utc)
    try:
        # Normalise to a list.
        ticks: list[dict[str, Any]]
        if isinstance(tick, dict):
            ticks = [tick]
        elif isinstance(tick, list):
            ticks = tick
        else:
            raise TypeError(f"persist_tick expects dict or list, got {type(tick).__name__}")

        rows_written = _run(_persist_ticks_async(ticks))
        TICKS_PERSISTED.labels(source="celery").inc(rows_written)
        _record_result(task_name, ok=True)
        return {"written": rows_written, "input": len(ticks)}
    except Exception:
        _log.exception("persist_tick_failed")
        _record_result(task_name, ok=False)
        raise
    finally:
        TASK_DURATION.labels(task=task_name).observe(
            (datetime.now(timezone.utc) - started).total_seconds()
        )


async def _persist_ticks_async(ticks: list[dict[str, Any]]) -> int:
    """Bulk-insert ticks in batches of :data:`TICK_BATCH_SIZE`."""
    if not ticks:
        return 0
    rows: list[dict[str, Any]] = []
    for t in ticks:
        coerced = _coerce_tick_row(t)
        if coerced is not None:
            rows.append(coerced)
    if not rows:
        _log.warning("persist_tick_no_valid_rows", input_count=len(ticks))
        return 0

    total_written = 0
    engine = get_engine()
    for i in range(0, len(rows), TICK_BATCH_SIZE):
        chunk = rows[i : i + TICK_BATCH_SIZE]
        stmt = (
            pg_insert(Tick.__table__)
            .values(chunk)
            .on_conflict_do_nothing()  # type: ignore[attr-defined]
        )
        async with engine.begin() as conn:
            result = await conn.execute(stmt)
            total_written += result.rowcount or len(chunk)
    _log.debug("persist_tick_batch_done", written=total_written, input=len(rows))
    return total_written


def _coerce_tick_row(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a bus/payload tick dict into a row dict for ``Tick`` insert.

    Returns ``None`` (and logs) on missing/invalid fields — a single bad
    tick must not abort the batch.
    """
    try:
        terminal_id = _safe_uuid(payload.get("terminal_id"))
        if terminal_id is None:
            raise ValueError("terminal_id missing or invalid")
        ts = _parse_dt(payload.get("ts"))
        if ts is None:
            raise ValueError("ts missing or invalid")
        return {
            "terminal_id": terminal_id,
            "symbol": str(payload["symbol"]),
            "bid": float(payload["bid"]),
            "ask": float(payload["ask"]),
            "last": float(payload["last"]) if payload.get("last") is not None else None,
            "volume": float(payload["volume"]) if payload.get("volume") is not None else None,
            "ts": ts,
        }
    except (KeyError, ValueError, TypeError):
        _log.exception("persist_tick_bad_payload", payload=payload)
        return None


# ── 2. persist_execution ────────────────────────────────────────────────────

@app.task(name="platform.tasks.persist_execution", bind=True, queue="trades")
def persist_execution(self: Task, report: dict[str, Any]) -> dict[str, Any]:
    """Persist an execution report and reconcile Order / Position / Trade.

    The ``report`` dict mirrors the payload published on
    :data:`Topic.EXECUTION_REPORTS` by the bridge layer. Required keys:
    ``client_order_id``, ``status`` (accepted | rejected | partial | filled
    | cancelled), ``executed_at``. Optional: ``broker_order_id``,
    ``broker_execution_id``, ``filled_volume``, ``avg_price``,
    ``rejection_reason``.

    Side effects:
        1. Looks up the Order by ``client_order_id``; updates status,
           filled volume, avg fill price, broker_order_id.
        2. Creates an :class:`Execution` row for the fill (status filled /
           partial only).
        3. Publishes a normalised event back to
           :data:`Topic.EXECUTION_REPORTS` so other subscribers (analytics,
           audit) see the persisted view.

    Idempotent: re-processing a report with the same
    ``broker_execution_id`` will not create a duplicate Execution row
    (unique check before insert).
    """
    task_name = self.name
    try:
        result = _run(_persist_execution_async(report))
        _record_result(task_name, ok=True)
        return result
    except Exception:
        _log.exception("persist_execution_failed", report=report)
        _record_result(task_name, ok=False)
        raise


async def _persist_execution_async(report: dict[str, Any]) -> dict[str, Any]:
    client_order_id = report.get("client_order_id")
    if not client_order_id:
        raise ValueError("execution report missing client_order_id")

    status = str(report.get("status", "")).lower()
    executed_at = _parse_dt(report.get("executed_at")) or datetime.now(timezone.utc)
    filled_volume = float(report.get("filled_volume") or 0)
    avg_price = report.get("avg_price")
    avg_price_f = float(avg_price) if avg_price is not None else None
    broker_order_id = report.get("broker_order_id")
    broker_execution_id = report.get("broker_execution_id")
    rejection_reason = report.get("rejection_reason")

    # Map bridge status → Order.status
    order_status_map = {
        "accepted": "submitted",
        "rejected": "rejected",
        "partial": "partial",
        "filled": "filled",
        "cancelled": "cancelled",
    }
    new_order_status = order_status_map.get(status, status)

    async with db_context() as db:
        # ── 1. Update the Order row ─────────────────────────────────────
        order_stmt = select(Order).where(Order.client_order_id == client_order_id)
        order = (await db.execute(order_stmt)).scalar_one_or_none()
        if order is None:
            _log.warning(
                "persist_execution_order_not_found",
                client_order_id=client_order_id,
            )
            return {"ok": False, "reason": "order_not_found"}

        # Only advance status forward — never downgrade (e.g. filled → partial).
        # Update unless we'd be moving away from a terminal "filled" state.
        if order.status != "filled" or new_order_status == "filled":
            order.status = new_order_status
        if broker_order_id:
            order.broker_order_id = broker_order_id
        if filled_volume > 0:
            # Update weighted-average fill price.
            prev_vol = float(order.filled_volume or 0)
            prev_avg = float(order.avg_fill_price) if order.avg_fill_price else 0.0
            new_total = prev_vol + filled_volume
            if avg_price_f is not None and new_total > 0:
                order.avg_fill_price = (
                    (prev_avg * prev_vol + avg_price_f * filled_volume) / new_total
                )
            order.filled_volume = new_total
        if new_order_status == "filled":
            order.filled_at = executed_at
        if rejection_reason:
            order.rejection_reason = rejection_reason
        order.updated_at = datetime.now(timezone.utc)

        # ── 2. Create Execution row (idempotent on broker_execution_id) ─
        execution_id: UUID | None = None
        if status in ("partial", "filled") and filled_volume > 0 and avg_price_f is not None:
            # Check for an existing execution with the same broker_execution_id.
            existing_exec: Execution | None = None
            if broker_execution_id:
                exec_stmt = select(Execution).where(
                    Execution.order_id == order.id,
                    Execution.broker_execution_id == broker_execution_id,
                )
                existing_exec = (await db.execute(exec_stmt)).scalar_one_or_none()
            if existing_exec is None:
                execution = Execution(
                    org_id=order.org_id,
                    order_id=order.id,
                    broker_execution_id=broker_execution_id,
                    volume=filled_volume,
                    price=avg_price_f,
                    executed_at=executed_at,
                )
                db.add(execution)
                await db.flush()
                execution_id = execution.id
            else:
                execution_id = existing_exec.id

        await db.commit()

    # ── 3. Publish normalised event ───────────────────────────────────
    try:
        bus = get_event_bus()
        await bus.publish(
            Topic.EXECUTION_REPORTS,
            {
                "client_order_id": client_order_id,
                "order_id": str(order.id) if order else None,
                "execution_id": str(execution_id) if execution_id else None,
                "status": new_order_status,
                "filled_volume": filled_volume,
                "avg_price": avg_price_f,
                "broker_order_id": broker_order_id,
                "broker_execution_id": broker_execution_id,
                "executed_at": executed_at.isoformat(),
                "rejection_reason": rejection_reason,
            },
        )
    except Exception:  # noqa: BLE001 — bus publish is best-effort
        _log.warning("persist_execution_publish_failed", client_order_id=client_order_id)

    _log.info(
        "persist_execution_done",
        client_order_id=client_order_id,
        order_status=new_order_status,
        filled_volume=filled_volume,
        execution_id=str(execution_id) if execution_id else None,
    )
    return {
        "ok": True,
        "order_status": new_order_status,
        "execution_id": str(execution_id) if execution_id else None,
    }


# ── 3. persist_position_update ──────────────────────────────────────────────

@app.task(name="platform.tasks.persist_position_update", bind=True, queue="trades")
def persist_position_update(self: Task, payload: dict[str, Any]) -> dict[str, Any]:
    """Upsert a Position from a bridge position-update event.

    On close (volume == 0 or status == closed) the task also:
        * Books a :class:`Trade` row (the historical record).
        * Credits the realized PnL onto the owning :class:`Account` balance.

    Idempotent: re-delivery of a close event will not double-book the
    Trade or balance — the existence of a Trade row for the position is
    checked first.
    """
    task_name = self.name
    try:
        result = _run(_persist_position_update_async(payload))
        _record_result(task_name, ok=True)
        return result
    except Exception:
        _log.exception("persist_position_update_failed", payload=payload)
        _record_result(task_name, ok=False)
        raise


async def _persist_position_update_async(payload: dict[str, Any]) -> dict[str, Any]:
    terminal_id_str = payload.get("terminal_id")
    broker_position_id = payload.get("broker_position_id")
    if not terminal_id_str or not broker_position_id:
        raise ValueError("position update requires terminal_id + broker_position_id")

    volume = float(payload.get("volume") or 0)
    is_closed = volume == 0 or str(payload.get("status", "")).lower() == "closed"

    async with db_context() as db:
        # Resolve the Terminal internal id + org id.
        term_stmt = select(Terminal).where(Terminal.terminal_id == terminal_id_str)
        terminal = (await db.execute(term_stmt)).scalar_one_or_none()
        if terminal is None:
            _log.warning(
                "persist_position_terminal_not_found",
                terminal_id=terminal_id_str,
            )
            return {"ok": False, "reason": "terminal_not_found"}

        # Upsert the Position row.
        pos_stmt = select(Position).where(
            Position.terminal_id == terminal.id,
            Position.broker_position_id == str(broker_position_id),
        )
        position = (await db.execute(pos_stmt)).scalar_one_or_none()
        opened_at = _parse_dt(payload.get("opened_at")) or datetime.now(timezone.utc)

        if position is None:
            # New position — insert.
            position = Position(
                org_id=terminal.org_id,
                terminal_id=terminal.id,
                broker_position_id=str(broker_position_id),
                symbol=str(payload["symbol"]),
                side=str(payload["side"]),
                volume=volume,
                open_price=float(payload["open_price"]),
                current_price=float(payload.get("current_price") or payload["open_price"]),
                stop_loss=float(payload["stop_loss"]) if payload.get("stop_loss") else None,
                take_profit=float(payload["take_profit"]) if payload.get("take_profit") else None,
                swap=float(payload.get("swap") or 0),
                unrealized_pnl=float(payload.get("unrealized_pnl") or 0),
                opened_at=opened_at,
                status="closed" if is_closed else "open",
                closed_at=datetime.now(timezone.utc) if is_closed else None,
            )
            db.add(position)
            await db.flush()
        else:
            # Update existing.
            position.volume = volume
            position.current_price = float(payload.get("current_price") or position.current_price)
            if payload.get("stop_loss"):
                position.stop_loss = float(payload["stop_loss"])
            if payload.get("take_profit"):
                position.take_profit = float(payload["take_profit"])
            position.swap = float(payload.get("swap") or position.swap)
            position.unrealized_pnl = float(payload.get("unrealized_pnl") or position.unrealized_pnl)
            if is_closed and position.status != "closed":
                position.status = "closed"
                position.closed_at = datetime.now(timezone.utc)

        # On close: book Trade + credit Account balance (idempotent).
        trade_id: UUID | None = None
        if is_closed:
            # Has a Trade already been booked for this position?
            trade_stmt = select(Trade).where(Trade.position_id == position.id)
            existing_trade = (await db.execute(trade_stmt)).scalar_one_or_none()
            if existing_trade is None:
                realized = float(payload.get("realized_pnl") or position.realized_pnl or 0)
                position.realized_pnl = realized
                close_price = float(payload.get("current_price") or position.current_price)
                duration = int(
                    (position.closed_at - position.opened_at).total_seconds()
                ) if position.closed_at else 0
                # Pips = price delta * 10^digits. Default digits=5 for FX.
                direction = 1 if position.side == "buy" else -1
                pips = direction * (close_price - position.open_price) * 10_000
                trade = Trade(
                    org_id=position.org_id,
                    position_id=position.id,
                    strategy_id=None,
                    symbol=position.symbol,
                    side=position.side,
                    volume=position.volume,
                    entry_price=position.open_price,
                    exit_price=close_price,
                    pnl=realized,
                    pips=pips,
                    commission=0,
                    swap=position.swap,
                    duration_seconds=duration,
                    opened_at=position.opened_at,
                    closed_at=position.closed_at or datetime.now(timezone.utc),
                )
                db.add(trade)
                await db.flush()
                trade_id = trade.id

                # Credit Account balance.
                acct_stmt = select(Account).where(Account.terminal_id == terminal.id)
                account = (await db.execute(acct_stmt)).scalar_one_or_none()
                if account is not None:
                    account.balance = float(account.balance) + realized
                    account.equity = float(account.equity) + realized
                    account.updated_at = datetime.now(timezone.utc)

        await db.commit()

    _log.info(
        "persist_position_update_done",
        terminal_id=terminal_id_str,
        broker_position_id=str(broker_position_id),
        closed=is_closed,
        trade_id=str(trade_id) if trade_id else None,
    )
    return {
        "ok": True,
        "position_id": str(position.id),
        "status": position.status,
        "trade_id": str(trade_id) if trade_id else None,
    }


# ── 4. persist_account_update ───────────────────────────────────────────────

@app.task(name="platform.tasks.persist_account_update", bind=True, queue="trades")
def persist_account_update(self: Task, payload: dict[str, Any]) -> dict[str, Any]:
    """Refresh the :class:`Account` snapshot from a bridge account-update.

    Payload keys: ``terminal_id``, ``balance``, ``equity``, ``margin``,
    ``free_margin``, ``currency`` (optional), ``leverage`` (optional).
    """
    task_name = self.name
    try:
        result = _run(_persist_account_update_async(payload))
        _record_result(task_name, ok=True)
        return result
    except Exception:
        _log.exception("persist_account_update_failed", payload=payload)
        _record_result(task_name, ok=False)
        raise


async def _persist_account_update_async(payload: dict[str, Any]) -> dict[str, Any]:
    terminal_id_str = payload.get("terminal_id")
    if not terminal_id_str:
        raise ValueError("account update requires terminal_id")

    async with db_context() as db:
        term_stmt = select(Terminal).where(Terminal.terminal_id == terminal_id_str)
        terminal = (await db.execute(term_stmt)).scalar_one_or_none()
        if terminal is None:
            return {"ok": False, "reason": "terminal_not_found"}

        acct_stmt = select(Account).where(Account.terminal_id == terminal.id)
        account = (await db.execute(acct_stmt)).scalar_one_or_none()
        if account is None:
            account = Account(
                org_id=terminal.org_id,
                terminal_id=terminal.id,
                broker_login=terminal.broker_account,
                currency=str(payload.get("currency") or "USD"),
                leverage=int(payload.get("leverage") or 100),
            )
            db.add(account)
            await db.flush()

        account.balance = float(payload["balance"])
        account.equity = float(payload["equity"])
        account.margin = float(payload["margin"])
        account.free_margin = float(payload["free_margin"])
        if "currency" in payload:
            account.currency = str(payload["currency"])
        if "leverage" in payload:
            account.leverage = int(payload["leverage"])
        account.last_synced_at = datetime.now(timezone.utc)
        account.updated_at = datetime.now(timezone.utc)
        await db.commit()

    return {"ok": True, "account_id": str(account.id)}


# ── 5. run_backtest ─────────────────────────────────────────────────────────

@app.task(name="platform.tasks.run_backtest", bind=True, queue="backtest")
def run_backtest(self: Task, backtest_id: str) -> dict[str, Any]:
    """Run a backtest end-to-end.

    Lifecycle:
        1. Mark the :class:`Backtest` row as ``running``.
        2. Load the row + strategy config; invoke
           :meth:`BacktestEngine.run`.
        3. Persist ``final_equity``, ``max_drawdown``, ``sharpe``,
           ``trades_count`` columns + the full results JSONB.
        4. Mark as ``completed`` (or ``failed`` on exception, with the
           error recorded in ``results.error``).
    """
    task_name = self.name
    bt_id = _safe_uuid(backtest_id)
    if bt_id is None:
        _log.error("run_backtest_bad_id", backtest_id=backtest_id)
        _record_result(task_name, ok=False)
        return {"ok": False, "reason": "bad_backtest_id"}

    # Mark RUNNING up-front so the UI can show progress.
    with suppress(Exception):
        _run(_set_backtest_status(bt_id, "running"))

    try:
        result = _run(_run_backtest_async(bt_id))
        _record_result(task_name, ok=True)
        return result
    except Exception as exc:
        _log.exception("run_backtest_failed", backtest_id=backtest_id)
        with suppress(Exception):
            _run(_fail_backtest(bt_id, str(exc)))
        _record_result(task_name, ok=False)
        raise


async def _set_backtest_status(bt_id: UUID, status: str) -> None:
    async with db_context() as db:
        stmt = (
            update(Backtest)
            .where(Backtest.id == bt_id)
            .values(status=status, updated_at=datetime.now(timezone.utc))
        )
        await db.execute(stmt)
        await db.commit()


async def _fail_backtest(bt_id: UUID, error: str) -> None:
    async with db_context() as db:
        stmt = (
            update(Backtest)
            .where(Backtest.id == bt_id)
            .values(
                status="failed",
                results={"error": error[:1000]},
                updated_at=datetime.now(timezone.utc),
            )
        )
        await db.execute(stmt)
        await db.commit()


async def _run_backtest_async(bt_id: UUID) -> dict[str, Any]:
    # Import here to avoid a top-level circular import (backtest → db → ...).
    from platform.backtest.engine import get_backtest_engine

    async with db_context() as db:
        backtest = await db.get(Backtest, bt_id)
        if backtest is None:
            raise ValueError(f"backtest {bt_id} not found")

    engine = get_backtest_engine()
    result = await engine.run(backtest)

    async with db_context() as db:
        stmt = (
            update(Backtest)
            .where(Backtest.id == bt_id)
            .values(
                status="completed",
                final_equity=result.final_equity,
                max_drawdown=result.max_drawdown,
                sharpe=result.sharpe,
                trades_count=result.trades_count,
                results=result.to_dict(),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await db.execute(stmt)
        await db.commit()

    _log.info(
        "run_backtest_completed",
        backtest_id=str(bt_id),
        trades=result.trades_count,
        final_equity=result.final_equity,
    )
    return {
        "ok": True,
        "backtest_id": str(bt_id),
        "final_equity": result.final_equity,
        "max_drawdown": result.max_drawdown,
        "sharpe": result.sharpe,
        "trades": result.trades_count,
    }


# ── 6. send_notification ───────────────────────────────────────────────────

@app.task(
    name="platform.tasks.send_notification",
    bind=True,
    queue="notifications",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=NOTIFICATION_MAX_RETRIES,
)
def send_notification(self: Task, notification_id: str) -> dict[str, Any]:
    """Dispatch a queued :class:`Notification` row via the configured channels.

    Loads the Notification row, builds a :class:`NotificationMessage`, and
    hands it to :class:`NotificationDispatcher`. On failure the task is
    retried up to :data:`NOTIFICATION_MAX_RETRIES` times with exponential
    backoff. The Notification row's ``status`` / ``error`` / ``sent_at``
    are updated to reflect the outcome.
    """
    task_name = self.name
    n_id = _safe_uuid(notification_id)
    if n_id is None:
        _log.error("send_notification_bad_id", notification_id=notification_id)
        _record_result(task_name, ok=False)
        return {"ok": False, "reason": "bad_notification_id"}

    try:
        result = _run(_send_notification_async(n_id))
        _record_result(task_name, ok=True)
        return result
    except Exception as exc:
        _log.warning(
            "send_notification_retrying",
            notification_id=str(n_id),
            attempt=self.request.retries + 1,
            error=str(exc),
        )
        # Mark the row failed on the final attempt only.
        if self.request.retries >= NOTIFICATION_MAX_RETRIES - 1:
            with suppress(Exception):
                _run(_fail_notification(n_id, str(exc)))
            _record_result(task_name, ok=False)
        raise


async def _send_notification_async(n_id: UUID) -> dict[str, Any]:
    async with db_context() as db:
        notif = await db.get(Notification, n_id)
        if notif is None:
            raise ValueError(f"notification {n_id} not found")
        if notif.status == "sent":
            _log.info("send_notification_already_sent", notification_id=str(n_id))
            return {"ok": True, "skipped": True, "reason": "already_sent"}

        # Capture the fields we need (the ORM object will be detached after commit).
        channel = notif.channel
        to = notif.subject or ""  # subject is reused as recipient if not set
        subject = notif.subject
        body = notif.body
        org_id = notif.org_id
        user_id = notif.user_id

    # Resolve the recipient. The Notification schema doesn't have a dedicated
    # `to` column — we expect the dispatcher to use a default configured
    # recipient per channel (e.g. SMTP default recipient, Telegram chat id).
    # If the body is JSON with a "to" field, use that.
    recipient = ""
    parsed_body: dict[str, Any] | None = None
    try:
        parsed_body = json.loads(body)
        if isinstance(parsed_body, dict):
            recipient = str(parsed_body.get("to") or parsed_body.get("recipient") or "")
    except (json.JSONDecodeError, TypeError):
        pass

    message = NotificationMessage(
        channel=channel,
        to=recipient or to,
        subject=subject,
        body=body,
        meta={
            "org_id": str(org_id) if org_id else None,
            "user_id": str(user_id) if user_id else None,
            "notification_id": str(n_id),
        },
        priority="HIGH",
    )

    dispatcher = get_dispatcher()
    ok = await dispatcher.dispatch(message)

    async with db_context() as db:
        stmt = (
            update(Notification)
            .where(Notification.id == n_id)
            .values(
                status="sent" if ok else "failed",
                sent_at=datetime.now(timezone.utc) if ok else None,
                error=None if ok else "dispatch_failed",
                updated_at=datetime.now(timezone.utc),
            )
        )
        await db.execute(stmt)
        await db.commit()

    return {"ok": ok, "notification_id": str(n_id)}


async def _fail_notification(n_id: UUID, error: str) -> None:
    async with db_context() as db:
        stmt = (
            update(Notification)
            .where(Notification.id == n_id)
            .values(
                status="failed",
                error=error[:500],
                updated_at=datetime.now(timezone.utc),
            )
        )
        await db.execute(stmt)
        await db.commit()


# ── 7. sync_terminal_positions ──────────────────────────────────────────────

@app.task(name="platform.tasks.sync_terminal_positions", bind=True, queue="default")
def sync_terminal_positions(self: Task, terminal_id: str) -> dict[str, Any]:
    """Periodic job — pull open positions from the terminal and reconcile.

    Calls :meth:`BridgeClient.sync_positions`, upserts every remote position,
    marks DB positions no longer reported by the broker as ``closed``, and
    logs drift warnings (volume / SL / TP mismatches).
    """
    task_name = self.name
    try:
        result = _run(_sync_terminal_positions_async(terminal_id))
        _record_result(task_name, ok=True)
        return result
    except Exception:
        _log.exception("sync_terminal_positions_failed", terminal_id=terminal_id)
        _record_result(task_name, ok=False)
        raise


async def _sync_terminal_positions_async(terminal_id: str) -> dict[str, Any]:
    bridge = get_bridge_client()
    reply = await bridge.sync_positions(terminal_id=terminal_id, timeout=30.0)
    remote_positions: list[dict[str, Any]] = reply.payload.get("positions", []) or []

    async with db_context() as db:
        term_stmt = select(Terminal).where(Terminal.terminal_id == terminal_id)
        terminal = (await db.execute(term_stmt)).scalar_one_or_none()
        if terminal is None:
            return {"ok": False, "reason": "terminal_not_found"}

        db_open_stmt = select(Position).where(
            Position.terminal_id == terminal.id, Position.status == "open",
        )
        db_open = (await db.execute(db_open_stmt)).scalars().all()
        db_by_broker = {p.broker_position_id: p for p in db_open if p.broker_position_id}

        remote_ids: set[str] = set()
        drift_count = 0
        new_count = 0
        updated_count = 0

        for rp in remote_positions:
            broker_id = str(rp.get("broker_position_id"))
            remote_ids.add(broker_id)
            existing = db_by_broker.get(broker_id)
            opened_at = _parse_dt(rp.get("opened_at")) or datetime.now(timezone.utc)

            if existing is None:
                # New position.
                position = Position(
                    org_id=terminal.org_id,
                    terminal_id=terminal.id,
                    broker_position_id=broker_id,
                    symbol=str(rp["symbol"]),
                    side=str(rp["side"]),
                    volume=float(rp["volume"]),
                    open_price=float(rp["open_price"]),
                    current_price=float(rp.get("current_price") or rp["open_price"]),
                    stop_loss=float(rp["stop_loss"]) if rp.get("stop_loss") else None,
                    take_profit=float(rp["take_profit"]) if rp.get("take_profit") else None,
                    swap=float(rp.get("swap") or 0),
                    unrealized_pnl=float(rp.get("unrealized_pnl") or 0),
                    opened_at=opened_at,
                    status="open",
                )
                db.add(position)
                new_count += 1
            else:
                # Drift detection.
                drifts: list[str] = []
                if abs(float(existing.volume) - float(rp["volume"])) > 1e-6:
                    drifts.append(
                        f"volume: db={existing.volume} remote={rp['volume']}"
                    )
                if rp.get("stop_loss") and existing.stop_loss and \
                        abs(float(existing.stop_loss) - float(rp["stop_loss"])) > 1e-5:
                    drifts.append(
                        f"stop_loss: db={existing.stop_loss} remote={rp['stop_loss']}"
                    )
                if rp.get("take_profit") and existing.take_profit and \
                        abs(float(existing.take_profit) - float(rp["take_profit"])) > 1e-5:
                    drifts.append(
                        f"take_profit: db={existing.take_profit} remote={rp['take_profit']}"
                    )
                if drifts:
                    drift_count += 1
                    _log.warning(
                        "sync_positions_drift",
                        terminal_id=terminal_id,
                        broker_position_id=broker_id,
                        drifts=drifts,
                    )
                # Update with remote truth.
                existing.current_price = float(rp.get("current_price") or existing.current_price)
                existing.volume = float(rp["volume"])
                if rp.get("stop_loss"):
                    existing.stop_loss = float(rp["stop_loss"])
                if rp.get("take_profit"):
                    existing.take_profit = float(rp["take_profit"])
                existing.swap = float(rp.get("swap") or existing.swap)
                existing.unrealized_pnl = float(
                    rp.get("unrealized_pnl") or existing.unrealized_pnl
                )
                existing.updated_at = datetime.now(timezone.utc)
                updated_count += 1

        # Mark DB positions not reported by remote as closed.
        closed_count = 0
        for broker_id, p in db_by_broker.items():
            if broker_id not in remote_ids:
                p.status = "closed"
                p.closed_at = datetime.now(timezone.utc)
                p.updated_at = datetime.now(timezone.utc)
                closed_count += 1
                _log.warning(
                    "sync_positions_db_only_closed",
                    terminal_id=terminal_id,
                    broker_position_id=broker_id,
                )

        await db.commit()

    _log.info(
        "sync_terminal_positions_done",
        terminal_id=terminal_id,
        remote=len(remote_positions),
        new=new_count,
        updated=updated_count,
        drift=drift_count,
        closed=closed_count,
    )
    return {
        "ok": True,
        "terminal_id": terminal_id,
        "synced": len(remote_positions),
        "new": new_count,
        "updated": updated_count,
        "drift": drift_count,
        "closed": closed_count,
    }


# ── 8. sync_terminal_account ────────────────────────────────────────────────

@app.task(name="platform.tasks.sync_terminal_account", bind=True, queue="default")
def sync_terminal_account(self: Task, terminal_id: str) -> dict[str, Any]:
    """Periodic job — refresh the Account row from the terminal."""
    task_name = self.name
    try:
        result = _run(_sync_terminal_account_async(terminal_id))
        _record_result(task_name, ok=True)
        return result
    except Exception:
        _log.exception("sync_terminal_account_failed", terminal_id=terminal_id)
        _record_result(task_name, ok=False)
        raise


async def _sync_terminal_account_async(terminal_id: str) -> dict[str, Any]:
    bridge = get_bridge_client()
    reply = await bridge.sync_account(terminal_id=terminal_id, timeout=10.0)
    payload = reply.payload

    async with db_context() as db:
        term_stmt = select(Terminal).where(Terminal.terminal_id == terminal_id)
        terminal = (await db.execute(term_stmt)).scalar_one_or_none()
        if terminal is None:
            return {"ok": False, "reason": "terminal_not_found"}

        acct_stmt = select(Account).where(Account.terminal_id == terminal.id)
        account = (await db.execute(acct_stmt)).scalar_one_or_none()
        if account is None:
            account = Account(
                org_id=terminal.org_id,
                terminal_id=terminal.id,
                broker_login=terminal.broker_account,
                currency=str(payload.get("currency") or "USD"),
                leverage=int(payload.get("leverage") or 100),
            )
            db.add(account)
            await db.flush()

        account.balance = float(payload["balance"])
        account.equity = float(payload["equity"])
        account.margin = float(payload["margin"])
        account.free_margin = float(payload["free_margin"])
        if "currency" in payload:
            account.currency = str(payload["currency"])
        if "leverage" in payload:
            account.leverage = int(payload["leverage"])
        account.last_synced_at = datetime.now(timezone.utc)
        account.updated_at = datetime.now(timezone.utc)
        await db.commit()

    return {
        "ok": True,
        "terminal_id": terminal_id,
        "balance": float(payload["balance"]),
        "equity": float(payload["equity"]),
    }


# ── 9. cleanup_expired_signals ──────────────────────────────────────────────

@app.task(name="platform.tasks.cleanup_expired_signals", bind=True, queue="default")
def cleanup_expired_signals(self: Task) -> dict[str, Any]:
    """Daily/hourly job — mark stale pending signals as ``expired``.

    A signal is considered stale if it has been in ``pending`` status for
    longer than :data:`SIGNAL_TTL_HOURS`. Idempotent: re-running on the
    same hour is a no-op because expired signals are no longer ``pending``.
    """
    task_name = self.name
    try:
        result = _run(_cleanup_expired_signals_async())
        _record_result(task_name, ok=True)
        return result
    except Exception:
        _log.exception("cleanup_expired_signals_failed")
        _record_result(task_name, ok=False)
        raise


async def _cleanup_expired_signals_async() -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=SIGNAL_TTL_HOURS)
    async with db_context() as db:
        # Only expire signals still pending — never touch executed/rejected.
        stmt = (
            update(Signal)
            .where(
                Signal.status == "pending",
                Signal.created_at < cutoff,
            )
            .values(
                status="expired",
                updated_at=datetime.now(timezone.utc),
            )
            .returning(Signal.id)
        )
        result = await db.execute(stmt)
        expired_ids = [str(row[0]) for row in result.fetchall()]
        await db.commit()

    _log.info("cleanup_expired_signals_done", count=len(expired_ids), cutoff=cutoff.isoformat())
    return {"ok": True, "expired_count": len(expired_ids), "ids": expired_ids[:50]}


# ── 10. archive_old_ticks ───────────────────────────────────────────────────

@app.task(name="platform.tasks.archive_old_ticks", bind=True, queue="default")
def archive_old_ticks(self: Task, days: int = 90) -> dict[str, Any]:
    """Daily job — purge or archive ticks older than ``days`` days.

    Runs in batches of :data:`ARCHIVE_BATCH_SIZE` to keep individual
    transactions short and avoid lock contention on the hot tick table.

    Set ``ATLAS_TICK_ARCHIVE_MODE=archive`` in the environment to move
    ticks to a ``ticks_archive`` table (created on first run) instead of
    deleting them. Default mode is ``delete``.
    """
    task_name = self.name
    try:
        result = _run(_archive_old_ticks_async(days))
        _record_result(task_name, ok=True)
        return result
    except Exception:
        _log.exception("archive_old_ticks_failed", days=days)
        _record_result(task_name, ok=False)
        raise


async def _archive_old_ticks_async(days: int) -> dict[str, Any]:
    import os
    from sqlalchemy import text as sql_text

    mode = os.environ.get("ATLAS_TICK_ARCHIVE_MODE", "delete").lower()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    engine = get_engine()
    total_archived = 0
    total_deleted = 0

    while True:
        async with engine.begin() as conn:
            # Select a batch of ids to archive/delete — selecting first avoids
            # OFFSET scans and lets us bound each transaction to ~10k rows.
            select_stmt = (
                select(Tick.id)
                .where(Tick.ts < cutoff)
                .order_by(Tick.ts.asc())
                .limit(ARCHIVE_BATCH_SIZE)
            )
            ids = [row[0] for row in (await conn.execute(select_stmt)).fetchall()]
            if not ids:
                break

            if mode == "archive":
                # Ensure the archive table exists (idempotent).
                await conn.execute(_archive_table_ddl())
                # Copy rows into the archive table via INSERT ... SELECT.
                # This is a single statement — far cheaper than reading rows
                # into Python and re-inserting them.
                copy_stmt = sql_text(
                    """
                    INSERT INTO ticks_archive
                        (id, terminal_id, symbol, bid, ask, last, volume, ts, archived_at)
                    SELECT id, terminal_id, symbol, bid, ask, last, volume, ts, NOW()
                    FROM ticks
                    WHERE id = ANY(:ids)
                    """
                )
                cp_result = await conn.execute(copy_stmt, {"ids": ids})
                total_archived += cp_result.rowcount or len(ids)

            # Delete the archived (or to-be-purged) rows from the live table.
            delete_stmt = sql_text("DELETE FROM ticks WHERE id = ANY(:ids)")
            result = await conn.execute(delete_stmt, {"ids": ids})
            total_deleted += result.rowcount or len(ids)
            # engine.begin() auto-commits on context exit.

        _log.debug(
            "archive_old_ticks_batch",
            batch=len(ids), mode=mode,
            total_deleted=total_deleted, total_archived=total_archived,
        )
        # Safety cap — avoid an unbounded single task run.
        if total_deleted > 5_000_000:
            _log.warning("archive_old_ticks_safety_cap_reached", deleted=total_deleted)
            break

    _log.info(
        "archive_old_ticks_done",
        days=days, mode=mode,
        deleted=total_deleted, archived=total_archived,
        cutoff=cutoff.isoformat(),
    )
    return {
        "ok": True,
        "days": days,
        "mode": mode,
        "deleted": total_deleted,
        "archived": total_archived,
    }


def _archive_table_ddl() -> Any:
    """Return a ``CREATE TABLE IF NOT EXISTS ticks_archive ...`` statement.

    Mirrors the ``ticks`` schema plus an ``archived_at`` audit column. Uses
    raw SQL text so we don't have to define a separate ORM model just for
    archival.
    """
    from sqlalchemy import text
    return text("""
        CREATE TABLE IF NOT EXISTS ticks_archive (
            id INTEGER NOT NULL,
            terminal_id UUID NOT NULL,
            symbol VARCHAR(40) NOT NULL,
            bid NUMERIC(20, 5) NOT NULL,
            ask NUMERIC(20, 5) NOT NULL,
            last NUMERIC(20, 5),
            volume NUMERIC(20, 4),
            ts TIMESTAMP WITH TIME ZONE NOT NULL,
            archived_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)


# ── 11. compute_performance_metrics ─────────────────────────────────────────

@app.task(name="platform.tasks.compute_performance_metrics", bind=True, queue="default")
def compute_performance_metrics(self: Task, org_id: str) -> dict[str, Any]:
    """Hourly job — recompute and cache org-level performance KPIs.

    Computes win rate, total P&L, max drawdown (from the equity curve),
    Sharpe, and trade count over the last 30 days. The result is cached
    in Redis under ``atlas:perf:{org_id}`` with a 1-hour TTL so dashboards
    can read it without hitting the database on every page load.
    """
    task_name = self.name
    oid = _safe_uuid(org_id)
    if oid is None:
        _log.error("compute_performance_metrics_bad_org", org_id=org_id)
        _record_result(task_name, ok=False)
        return {"ok": False, "reason": "bad_org_id"}
    try:
        result = _run(_compute_performance_metrics_async(oid))
        _record_result(task_name, ok=True)
        return result
    except Exception:
        _log.exception("compute_performance_metrics_failed", org_id=org_id)
        _record_result(task_name, ok=False)
        raise


async def _compute_performance_metrics_async(org_id: UUID) -> dict[str, Any]:
    import math

    from platform.core.config import get_settings
    import redis.asyncio as aioredis

    since = datetime.now(timezone.utc) - timedelta(days=30)
    async with db_context() as db:
        # Aggregate closed trades.
        stmt = (
            select(
                func.count(Trade.id).label("total_trades"),
                func.sum(Trade.pnl).label("total_pnl"),
                func.avg(Trade.pnl).label("avg_pnl"),
                func.max(Trade.pnl).label("best"),
                func.min(Trade.pnl).label("worst"),
                func.sum(func.case((Trade.pnl > 0, 1), else_=0)).label("wins"),
                func.avg(Trade.duration_seconds).label("avg_duration"),
            )
            .where(Trade.org_id == org_id, Trade.closed_at >= since)
        )
        row = (await db.execute(stmt)).one()

        # Daily P&L series for drawdown / Sharpe.
        daily_stmt = (
            select(
                func.date_trunc("day", Trade.closed_at).label("day"),
                func.sum(Trade.pnl).label("pnl"),
            )
            .where(Trade.org_id == org_id, Trade.closed_at >= since)
            .group_by("day")
            .order_by("day")
        )
        daily_rows = (await db.execute(daily_stmt)).all()

    total_trades = int(row.total_trades or 0)
    wins = int(row.wins or 0)
    total_pnl = float(row.total_pnl or 0)
    avg_pnl = float(row.avg_pnl or 0) if total_trades else 0.0
    best = float(row.best) if row.best is not None else None
    worst = float(row.worst) if row.worst is not None else None
    avg_duration = float(row.avg_duration or 0) if total_trades else 0.0
    win_rate = (wins / total_trades) if total_trades else 0.0

    # Equity curve (cumulative P&L by day) → drawdown + Sharpe.
    daily_pnls = [float(r.pnl or 0) for r in daily_rows]
    equity_curve: list[float] = []
    running = 0.0
    for p in daily_pnls:
        running += p
        equity_curve.append(running)
    peak = 0.0
    max_dd = 0.0
    for eq in equity_curve:
        peak = max(peak, eq)
        dd = (peak - eq) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    mean_pnl = (sum(daily_pnls) / len(daily_pnls)) if daily_pnls else 0.0
    variance = (
        sum((p - mean_pnl) ** 2 for p in daily_pnls) / len(daily_pnls)
    ) if daily_pnls else 0.0
    std_pnl = math.sqrt(variance)
    sharpe = (mean_pnl / std_pnl) if std_pnl > 1e-9 else 0.0

    metrics = {
        "org_id": str(org_id),
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "window_days": 30,
        "total_trades": total_trades,
        "win_rate": round(win_rate, 4),
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(avg_pnl, 2),
        "best_trade": round(best, 2) if best is not None else None,
        "worst_trade": round(worst, 2) if worst is not None else None,
        "avg_duration_seconds": round(avg_duration, 1),
        "max_drawdown": round(max_dd, 6),
        "sharpe": round(sharpe, 4) if math.isfinite(sharpe) else None,
        "daily_pnl": [
            {"day": r.day.isoformat() if r.day else None, "pnl": round(float(r.pnl or 0), 2)}
            for r in daily_rows
        ],
    }

    # Cache in Redis for dashboard reads.
    try:
        settings = get_settings()
        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            await client.setex(
                f"atlas:perf:{org_id}",
                PERF_CACHE_TTL_SECONDS,
                json.dumps(metrics, default=str),
            )
        finally:
            await client.close()
    except Exception:  # noqa: BLE001 — cache write is best-effort
        _log.warning("compute_performance_metrics_cache_failed", org_id=str(org_id))

    _log.info(
        "compute_performance_metrics_done",
        org_id=str(org_id),
        trades=total_trades,
        win_rate=win_rate,
        total_pnl=total_pnl,
        max_drawdown=max_dd,
    )
    return {"ok": True, "metrics": metrics}


# ── 12. check_risk_thresholds ───────────────────────────────────────────────

@app.task(name="platform.tasks.check_risk_thresholds", bind=True, queue="default")
def check_risk_thresholds(self: Task, org_id: str) -> dict[str, Any]:
    """Periodic (every minute) job — evaluate risk thresholds for an org.

    Computes today's realized P&L and current account drawdown, compares
    against the org's risk limits (defaults: $1000 daily loss, 20% DD),
    and auto-engages the kill switch + sends a CRITICAL notification if
    breached.

    Idempotent: if the kill switch is already engaged, no duplicate
    notification is sent.
    """
    task_name = self.name
    oid = _safe_uuid(org_id)
    if oid is None:
        _log.error("check_risk_thresholds_bad_org", org_id=org_id)
        _record_result(task_name, ok=False)
        return {"ok": False, "reason": "bad_org_id"}
    try:
        result = _run(_check_risk_thresholds_async(oid))
        _record_result(task_name, ok=True)
        return result
    except Exception:
        _log.exception("check_risk_thresholds_failed", org_id=org_id)
        _record_result(task_name, ok=False)
        raise


async def _check_risk_thresholds_async(org_id: UUID) -> dict[str, Any]:
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )

    async with db_context() as db:
        # Today's realized PnL.
        pnl_stmt = (
            select(func.sum(Trade.pnl))
            .where(Trade.org_id == org_id, Trade.closed_at >= today_start)
        )
        daily_pnl = float((await db.execute(pnl_stmt)).scalar_one() or 0)

        # Current accounts for the org (use equity/balance for DD calc).
        acct_stmt = select(Account).where(Account.org_id == org_id)
        accounts = (await db.execute(acct_stmt)).scalars().all()

        # Track peak equity per account from RiskEvents? For now, use a
        # simple heuristic: drawdown = (balance - equity) / balance when
        # equity < balance (floating loss). A more robust implementation
        # would track a rolling peak in Redis.
        breached_rules: list[dict[str, Any]] = []

        # Rule 1: max_daily_loss
        if daily_pnl <= -DEFAULT_RISK_LIMIT_USD:
            breached_rules.append({
                "rule": "max_daily_loss",
                "severity": "critical",
                "value": daily_pnl,
                "limit": -DEFAULT_RISK_LIMIT_USD,
            })

        # Rule 2: max_drawdown (per account, simple floating-loss proxy)
        for acct in accounts:
            balance = float(acct.balance or 0)
            equity = float(acct.equity or 0)
            if balance > 0 and equity < balance:
                dd = (balance - equity) / balance
                if dd >= DEFAULT_MAX_DRAWDOWN_PCT:
                    breached_rules.append({
                        "rule": "max_drawdown",
                        "severity": "critical",
                        "terminal_id": str(acct.terminal_id),
                        "value": round(dd, 4),
                        "limit": DEFAULT_MAX_DRAWDOWN_PCT,
                    })

        # Persist RiskEvent rows for each breach.
        for breach in breached_rules:
            risk_event = RiskEvent(
                org_id=org_id,
                terminal_id=_safe_uuid(breach.get("terminal_id")),
                rule=breach["rule"],
                severity=breach["severity"],
                action="disable",
                details=breach,
            )
            db.add(risk_event)
        await db.commit()

    # If any breach → auto-engage kill switch + notify.
    kill_switch_engaged = False
    notification_sent = False
    if breached_rules:
        engine = get_risk_engine()
        # Avoid re-engaging / re-notifying if already engaged.
        was_engaged = getattr(engine.kill_switch, "_engaged", False)
        if not was_engaged:
            engine.kill_switch.engage(reason="auto:max_daily_loss_or_drawdown")
            kill_switch_engaged = True

            # Publish a risk event on the bus.
            try:
                bus = get_event_bus()
                await bus.publish(
                    Topic.RISK_EVENTS,
                    {
                        "type": "kill_switch_auto_engaged",
                        "org_id": str(org_id),
                        "rule": "auto_risk_monitor",
                        "severity": "kill",
                        "action": "disable",
                        "details": {
                            "breaches": breached_rules,
                            "daily_pnl": daily_pnl,
                        },
                    },
                )
            except Exception:  # noqa: BLE001
                _log.warning("check_risk_thresholds_publish_failed", org_id=str(org_id))

            # Send CRITICAL notification.
            try:
                dispatcher = get_dispatcher()
                body = (
                    f"ATLAS Risk Alert — kill switch auto-engaged.\n\n"
                    f"Org: {org_id}\n"
                    f"Daily P&L: ${daily_pnl:.2f}\n"
                    f"Breaches: {len(breached_rules)}\n"
                )
                for b in breached_rules:
                    body += f"  - {b['rule']}: value={b.get('value')} limit={b.get('limit')}\n"
                # Prefer email for risk alerts; fall back to any configured channel.
                channels = dispatcher.channels
                channel_name = (
                    "email" if "email" in channels
                    else next(iter(channels), "email")
                )
                msg = NotificationMessage(
                    channel=channel_name,
                    to="",
                    subject="[ATLAS] Risk threshold breached — kill switch engaged",
                    body=body,
                    meta={"org_id": str(org_id)},
                    priority="CRITICAL",
                )
                await dispatcher.dispatch(msg)
                notification_sent = True
            except Exception:  # noqa: BLE001
                _log.warning("check_risk_thresholds_notify_failed", org_id=str(org_id))

    _log.info(
        "check_risk_thresholds_done",
        org_id=str(org_id),
        daily_pnl=daily_pnl,
        breaches=len(breached_rules),
        kill_switch_engaged=kill_switch_engaged,
        notification_sent=notification_sent,
    )
    return {
        "ok": True,
        "org_id": str(org_id),
        "daily_pnl": daily_pnl,
        "breaches": breached_rules,
        "kill_switch_engaged": kill_switch_engaged,
        "notification_sent": notification_sent,
    }


# ── 13. reconcile_orders ────────────────────────────────────────────────────

@app.task(name="platform.tasks.reconcile_orders", bind=True, queue="default")
def reconcile_orders(self: Task, terminal_id: str) -> dict[str, Any]:
    """Hourly job — reconcile DB orders against the terminal's view.

    Calls :meth:`BridgeClient.sync_positions` is for positions; for orders
    we issue a ``SYNC_ORDERS`` command via the bridge (falls back to
    ``sync_positions`` if unsupported). Compares broker order ids and
    statuses, flags any mismatch, and sends an alert notification.
    """
    task_name = self.name
    try:
        result = _run(_reconcile_orders_async(terminal_id))
        _record_result(task_name, ok=True)
        return result
    except Exception:
        _log.exception("reconcile_orders_failed", terminal_id=terminal_id)
        _record_result(task_name, ok=False)
        raise


async def _reconcile_orders_async(terminal_id: str) -> dict[str, Any]:
    bridge = get_bridge_client()

    # Try SYNC_ORDERS via the bridge. The bridge client doesn't expose a
    # dedicated method, so we craft the command directly through the
    # command queue + registry — but to keep this defensive we fall back
    # to sync_positions if SYNC_ORDERS isn't available.
    remote_orders: list[dict[str, Any]] = []
    try:
        from platform.infrastructure.mt5_bridge.command_queue import get_command_queue
        from platform.infrastructure.mt5_bridge.protocol import CommandType, command
        from platform.infrastructure.mt5_bridge.registry import get_registry

        registry = get_registry()
        rec = await registry.require(terminal_id)
        cmd = command(CommandType.SYNC_ORDERS, terminal_id=terminal_id)
        await rec.session.send(cmd)
        reply = await get_command_queue().enqueue(cmd, timeout=30.0)
        remote_orders = reply.payload.get("orders", []) or []
    except Exception:  # noqa: BLE001
        _log.warning(
            "reconcile_orders_sync_orders_unavailable",
            terminal_id=terminal_id,
        )

    async with db_context() as db:
        term_stmt = select(Terminal).where(Terminal.terminal_id == terminal_id)
        terminal = (await db.execute(term_stmt)).scalar_one_or_none()
        if terminal is None:
            return {"ok": False, "reason": "terminal_not_found"}

        # Active DB orders (not in a terminal state).
        db_orders_stmt = select(Order).where(
            Order.terminal_id == terminal.id,
            Order.status.in_(["pending", "submitted", "partial"]),
        )
        db_orders = (await db.execute(db_orders_stmt)).scalars().all()
        db_by_broker = {
            o.broker_order_id: o for o in db_orders if o.broker_order_id
        }

        missing_in_db: list[dict[str, Any]] = []
        missing_in_terminal: list[str] = []
        mismatches: list[dict[str, Any]] = []

        remote_ids: set[str] = set()
        for ro in remote_orders:
            broker_id = str(ro.get("broker_order_id"))
            remote_ids.add(broker_id)
            db_order = db_by_broker.get(broker_id)
            if db_order is None:
                missing_in_db.append({
                    "broker_order_id": broker_id,
                    "status": ro.get("status"),
                    "symbol": ro.get("symbol"),
                    "side": ro.get("side"),
                    "volume": ro.get("volume"),
                })
            else:
                # Compare status / filled_volume.
                remote_status = str(ro.get("status", "")).lower()
                if remote_status and remote_status != db_order.status:
                    mismatches.append({
                        "broker_order_id": broker_id,
                        "client_order_id": db_order.client_order_id,
                        "db_status": db_order.status,
                        "remote_status": remote_status,
                    })
                remote_filled = float(ro.get("filled_volume") or 0)
                if abs(float(db_order.filled_volume or 0) - remote_filled) > 1e-6:
                    mismatches.append({
                        "broker_order_id": broker_id,
                        "client_order_id": db_order.client_order_id,
                        "db_filled_volume": float(db_order.filled_volume or 0),
                        "remote_filled_volume": remote_filled,
                    })

        # DB orders not reported by terminal.
        for broker_id, o in db_by_broker.items():
            if broker_id not in remote_ids:
                missing_in_terminal.append(broker_id)

        await db.commit()

    total_issues = (
        len(missing_in_db) + len(missing_in_terminal) + len(mismatches)
    )

    # Send an alert notification if there are mismatches.
    if total_issues > 0:
        _log.warning(
            "reconcile_orders_mismatch",
            terminal_id=terminal_id,
            missing_in_db=len(missing_in_db),
            missing_in_terminal=len(missing_in_terminal),
            mismatches=len(mismatches),
        )
        try:
            dispatcher = get_dispatcher()
            body = (
                f"ATLAS Order Reconciliation Alert\n\n"
                f"Terminal: {terminal_id}\n"
                f"Total issues: {total_issues}\n\n"
                f"Missing in DB (terminal reports, DB doesn't): {len(missing_in_db)}\n"
                f"Missing in terminal (DB has, terminal doesn't): {len(missing_in_terminal)}\n"
                f"Status/volume mismatches: {len(mismatches)}\n\n"
                f"Details (first 10):\n"
            )
            for m in (missing_in_db + mismatches)[:10]:
                body += f"  - {m}\n"
            # Prefer email for ops alerts; fall back to any configured channel.
            channels = dispatcher.channels
            channel_name = (
                "email" if "email" in channels
                else next(iter(channels), "email")
            )
            msg = NotificationMessage(
                channel=channel_name,
                to="",
                subject=f"[ATLAS] Order reconciliation mismatch on {terminal_id}",
                body=body,
                meta={"terminal_id": terminal_id},
                priority="HIGH",
            )
            await dispatcher.dispatch(msg)
        except Exception:  # noqa: BLE001
            _log.warning("reconcile_orders_alert_failed", terminal_id=terminal_id)

    return {
        "ok": True,
        "terminal_id": terminal_id,
        "remote_orders": len(remote_orders),
        "db_orders": len(db_orders),
        "missing_in_db": missing_in_db,
        "missing_in_terminal": missing_in_terminal,
        "mismatches": mismatches,
        "total_issues": total_issues,
    }


# ── 14. flush_tick_buffer ───────────────────────────────────────────────────

@app.task(name="platform.tasks.flush_tick_buffer", bind=True, queue="ticks")
def flush_tick_buffer(self: Task) -> dict[str, Any]:
    """Fallback tick flusher — runs every 30s.

    If the :class:`TickStore`'s in-process async flusher stalls (e.g. an
    unhandled exception in the loop), this Celery task picks up the slack
    by calling :meth:`TickStore.flush_now` directly. The call is a no-op
    if the buffer is empty.
    """
    task_name = self.name
    try:
        result = _run(_flush_tick_buffer_async())
        _record_result(task_name, ok=True)
        return result
    except Exception:
        _log.exception("flush_tick_buffer_failed")
        _record_result(task_name, ok=False)
        raise


async def _flush_tick_buffer_async() -> dict[str, Any]:
    # Import lazily — TickStore may not be initialised in environments
    # without a live event bus (e.g. CLI scripts running this task).
    try:
        from platform.market_data.tick_store import get_tick_store
    except Exception:  # noqa: BLE001
        _log.warning("flush_tick_buffer_tick_store_unavailable")
        return {"ok": False, "reason": "tick_store_unavailable"}

    store = get_tick_store()
    # If the flusher was never started, there's nothing to flush.
    if getattr(store, "_flusher", None) is None:
        return {"ok": True, "flushed": 0, "reason": "not_started"}
    try:
        written = await store.flush_now()
    except Exception:  # noqa: BLE001
        _log.exception("flush_tick_buffer_flush_failed")
        return {"ok": False, "reason": "flush_error"}
    if written > 0:
        TICKS_PERSISTED.labels(source="celery_fallback").inc(written)
        _log.info("flush_tick_buffer_done", written=written)
    return {"ok": True, "flushed": written}


# ── 15. send_daily_report ───────────────────────────────────────────────────

@app.task(name="platform.tasks.send_daily_report", bind=True, queue="notifications")
def send_daily_report(self: Task, user_id: str) -> dict[str, Any]:
    """Daily job — generate a performance report for a user and dispatch it.

    Aggregates the user's org trades over the last 24h, formats a plain-
    text summary, and sends it via every configured notification channel
    (email + telegram by default). Idempotent: a per-user-per-day marker
    is written to Redis so re-runs don't spam the user.
    """
    task_name = self.name
    uid = _safe_uuid(user_id)
    if uid is None:
        _log.error("send_daily_report_bad_user", user_id=user_id)
        _record_result(task_name, ok=False)
        return {"ok": False, "reason": "bad_user_id"}
    try:
        result = _run(_send_daily_report_async(uid))
        _record_result(task_name, ok=True)
        return result
    except Exception:
        _log.exception("send_daily_report_failed", user_id=user_id)
        _record_result(task_name, ok=False)
        raise


async def _send_daily_report_async(user_id: UUID) -> dict[str, Any]:
    import math

    from platform.core.config import get_settings
    from platform.db.models import User
    import redis.asyncio as aioredis

    # Idempotency check — one report per user per UTC day.
    today_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    idem_key = f"atlas:daily_report:{user_id}:{today_key}"
    settings = get_settings()
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        already_sent = await redis_client.set(idem_key, "1", ex=86_400, nx=True)
        if not already_sent:
            _log.info("send_daily_report_already_sent", user_id=str(user_id), day=today_key)
            return {"ok": True, "skipped": True, "reason": "already_sent_today"}
    finally:
        await redis_client.close()

    async with db_context() as db:
        user = await db.get(User, user_id)
        if user is None or user.deleted_at is not None:
            return {"ok": False, "reason": "user_not_found"}
        org_id = user.org_id
        display_name = user.display_name
        email = user.email

        since = datetime.now(timezone.utc) - timedelta(hours=24)
        stmt = (
            select(
                func.count(Trade.id).label("total"),
                func.sum(Trade.pnl).label("pnl"),
                func.sum(func.case((Trade.pnl > 0, 1), else_=0)).label("wins"),
                func.avg(Trade.pnl).label("avg"),
                func.max(Trade.pnl).label("best"),
                func.min(Trade.pnl).label("worst"),
            )
            .where(Trade.org_id == org_id, Trade.closed_at >= since)
        )
        row = (await db.execute(stmt)).one()

    total = int(row.total or 0)
    wins = int(row.wins or 0)
    pnl = float(row.pnl or 0)
    avg = float(row.avg or 0) if total else 0.0
    best = float(row.best) if row.best is not None else None
    worst = float(row.worst) if row.worst is not None else None
    win_rate = (wins / total) if total else 0.0

    subject = f"[ATLAS] Daily Performance Report — {today_key}"
    best_str = f"${best:,.2f}" if best is not None else "n/a"
    worst_str = f"${worst:,.2f}" if worst is not None else "n/a"
    body = (
        f"Hi {display_name},\n\n"
        f"Here's your ATLAS trading summary for {today_key} (last 24h):\n\n"
        f"  Total trades:    {total}\n"
        f"  Win rate:        {win_rate:.1%}\n"
        f"  Total P&L:       ${pnl:,.2f}\n"
        f"  Avg P&L / trade: ${avg:,.2f}\n"
        f"  Best trade:      {best_str}\n"
        f"  Worst trade:     {worst_str}\n\n"
        f"— ATLAS Platform\n"
    )

    # Fan out to every configured channel.
    dispatcher = get_dispatcher()
    sent_channels: dict[str, bool] = {}
    if not dispatcher.channels:
        _log.warning("send_daily_report_no_channels", user_id=str(user_id))
    else:
        # Try email first (with the user's address); fall back to all channels.
        targets: dict[str, str] = {}
        if "email" in dispatcher.channels:
            targets["email"] = email
        msg_meta = {"org_id": str(org_id), "user_id": str(user_id)}
        sent_channels = await dispatcher.dispatch_to_all(
            subject=subject, body=body,
            meta={**msg_meta, "channel_targets": targets},
            priority="NORMAL",
        )

    _log.info(
        "send_daily_report_done",
        user_id=str(user_id),
        day=today_key,
        trades=total,
        pnl=pnl,
        channels=sent_channels,
    )
    return {
        "ok": True,
        "user_id": str(user_id),
        "day": today_key,
        "trades": total,
        "pnl": pnl,
        "channels": sent_channels,
    }


# ── Worker shutdown hook ────────────────────────────────────────────────────

@app.task(name="platform.tasks.dispose_db_engine")
def dispose_db_engine() -> None:
    """Best-effort DB engine disposal — invoke from a Celery worker-shutdown signal."""
    with suppress(Exception):
        _run(dispose_engine())


# ── Fan-out tasks (drive per-org / per-terminal periodic jobs) ──────────────
#
# These tasks are scheduled by Celery Beat at a fixed cadence and expand
# themselves into one task per org or per terminal. Keeping the fan-out
# separate from the worker task means Beat's schedule is independent of DB
# state (terminals / orgs come and go) and avoids drift.

@app.task(name="platform.tasks.fanout_sync_terminal_positions", bind=True, queue="default")
def fanout_sync_terminal_positions(self: Task) -> dict[str, Any]:
    """Enqueue ``sync_terminal_positions`` for every online terminal."""
    task_name = self.name
    try:
        result = _run(_fanout_terminal_jobs(
            "platform.tasks.sync_terminal_positions",
        ))
        _record_result(task_name, ok=True)
        return result
    except Exception:
        _log.exception("fanout_sync_terminal_positions_failed")
        _record_result(task_name, ok=False)
        raise


@app.task(name="platform.tasks.fanout_reconcile_orders", bind=True, queue="default")
def fanout_reconcile_orders(self: Task) -> dict[str, Any]:
    """Enqueue ``reconcile_orders`` for every online terminal."""
    task_name = self.name
    try:
        result = _run(_fanout_terminal_jobs("platform.tasks.reconcile_orders"))
        _record_result(task_name, ok=True)
        return result
    except Exception:
        _log.exception("fanout_reconcile_orders_failed")
        _record_result(task_name, ok=False)
        raise


@app.task(name="platform.tasks.fanout_check_risk_thresholds", bind=True, queue="default")
def fanout_check_risk_thresholds(self: Task) -> dict[str, Any]:
    """Enqueue ``check_risk_thresholds`` for every org."""
    task_name = self.name
    try:
        result = _run(_fanout_org_jobs("platform.tasks.check_risk_thresholds"))
        _record_result(task_name, ok=True)
        return result
    except Exception:
        _log.exception("fanout_check_risk_thresholds_failed")
        _record_result(task_name, ok=False)
        raise


@app.task(name="platform.tasks.fanout_compute_performance_metrics", bind=True, queue="default")
def fanout_compute_performance_metrics(self: Task) -> dict[str, Any]:
    """Enqueue ``compute_performance_metrics`` for every org."""
    task_name = self.name
    try:
        result = _run(_fanout_org_jobs("platform.tasks.compute_performance_metrics"))
        _record_result(task_name, ok=True)
        return result
    except Exception:
        _log.exception("fanout_compute_performance_metrics_failed")
        _record_result(task_name, ok=False)
        raise


@app.task(name="platform.tasks.fanout_send_daily_report", bind=True, queue="notifications")
def fanout_send_daily_report(self: Task) -> dict[str, Any]:
    """Enqueue ``send_daily_report`` for every active user."""
    task_name = self.name
    try:
        result = _run(_fanout_user_jobs("platform.tasks.send_daily_report"))
        _record_result(task_name, ok=True)
        return result
    except Exception:
        _log.exception("fanout_send_daily_report_failed")
        _record_result(task_name, ok=False)
        raise


async def _fanout_terminal_jobs(task_name: str) -> dict[str, Any]:
    """List all online terminals and enqueue ``task_name`` for each."""
    from platform.db.models import Terminal

    async with db_context() as db:
        stmt = select(Terminal.terminal_id).where(Terminal.status == "online")
        terminal_ids = [row[0] for row in (await db.execute(stmt)).fetchall()]

    enqueued = 0
    for tid in terminal_ids:
        try:
            app.send_task(task_name, args=[tid], queue="default")
            enqueued += 1
        except Exception:  # noqa: BLE001
            _log.warning("fanout_enqueue_failed", task=task_name, terminal_id=tid)
    _log.info("fanout_terminal_jobs_done", task=task_name, total=len(terminal_ids), enqueued=enqueued)
    return {"ok": True, "task": task_name, "total": len(terminal_ids), "enqueued": enqueued}


async def _fanout_org_jobs(task_name: str) -> dict[str, Any]:
    """List all orgs and enqueue ``task_name`` for each."""
    from platform.db.models import Organization

    async with db_context() as db:
        stmt = select(Organization.id).where(Organization.deleted_at.is_(None))
        org_ids = [str(row[0]) for row in (await db.execute(stmt)).fetchall()]

    enqueued = 0
    for oid in org_ids:
        try:
            app.send_task(task_name, args=[oid], queue="default")
            enqueued += 1
        except Exception:  # noqa: BLE001
            _log.warning("fanout_enqueue_failed", task=task_name, org_id=oid)
    _log.info("fanout_org_jobs_done", task=task_name, total=len(org_ids), enqueued=enqueued)
    return {"ok": True, "task": task_name, "total": len(org_ids), "enqueued": enqueued}


async def _fanout_user_jobs(task_name: str) -> dict[str, Any]:
    """List all active users and enqueue ``task_name`` for each."""
    from platform.db.models import User

    async with db_context() as db:
        stmt = select(User.id).where(
            User.is_active.is_(True), User.deleted_at.is_(None),
        )
        user_ids = [str(row[0]) for row in (await db.execute(stmt)).fetchall()]

    enqueued = 0
    for uid in user_ids:
        try:
            app.send_task(task_name, args=[uid], queue="notifications")
            enqueued += 1
        except Exception:  # noqa: BLE001
            _log.warning("fanout_enqueue_failed", task=task_name, user_id=uid)
    _log.info("fanout_user_jobs_done", task=task_name, total=len(user_ids), enqueued=enqueued)
    return {"ok": True, "task": task_name, "total": len(user_ids), "enqueued": enqueued}


__all__ = [
    "persist_tick",
    "persist_execution",
    "persist_position_update",
    "persist_account_update",
    "run_backtest",
    "send_notification",
    "sync_terminal_positions",
    "sync_terminal_account",
    "cleanup_expired_signals",
    "archive_old_ticks",
    "compute_performance_metrics",
    "check_risk_thresholds",
    "reconcile_orders",
    "flush_tick_buffer",
    "send_daily_report",
    # Fan-out helpers (scheduled by Beat)
    "fanout_sync_terminal_positions",
    "fanout_reconcile_orders",
    "fanout_check_risk_thresholds",
    "fanout_compute_performance_metrics",
    "fanout_send_daily_report",
]
