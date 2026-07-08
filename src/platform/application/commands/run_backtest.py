"""Run a backtest — create the row, dispatch the Celery task, return immediately.

Vertical slice:

  API → command → insert Backtest row (status=PENDING)
        → enqueue Celery task ``platform.tasks.run_backtest`` with the backtest_id
        → return the backtest_id (caller polls /backtests/{id} for results)

The actual simulation runs out-of-process on a Celery worker (see
``platform.infrastructure.celery_app.run_backtest``). The HTTP request never
blocks on the simulation.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel

from platform.core.logging import get_logger
from platform.db.models import Backtest
from platform.db.session import db_context
from platform.events.bus import get_event_bus
from platform.events.topics import Topic

_log = get_logger(__name__)


# ── Command + DTO ──────────────────────────────────────────────────────────


class RunBacktestCommand(BaseModel):
    org_id: UUID
    user_id: UUID
    strategy_id: UUID
    symbol: str
    timeframe: str
    start: datetime
    end: datetime
    initial_capital: float = 10_000.0
    config: dict[str, Any] = {}


class RunBacktestResult(BaseModel):
    backtest_id: UUID
    status: str
    queued: bool


# ── Handler ─────────────────────────────────────────────────────────────────


async def handle_run_backtest(cmd: RunBacktestCommand) -> RunBacktestResult:
    """Persist a PENDING Backtest row and enqueue the worker task."""
    if cmd.end <= cmd.start:
        from platform.core.exceptions import ValidationError

        raise ValidationError("end must be after start")
    if cmd.initial_capital <= 0:
        from platform.core.exceptions import ValidationError

        raise ValidationError("initial_capital must be positive")

    backtest_id = uuid4()
    async with db_context() as db:
        bt = Backtest(
            id=backtest_id,
            org_id=cmd.org_id,
            strategy_id=cmd.strategy_id,
            symbol=cmd.symbol,
            timeframe=cmd.timeframe,
            start=cmd.start,
            end=cmd.end,
            initial_capital=cmd.initial_capital,
            config=cmd.config,
            status="pending",  # PENDING → running → completed | failed
        )
        db.add(bt)
        await db.commit()

    # Dispatch to Celery — fail-soft: if the broker is unreachable (dev / CI)
    # we leave the row as PENDING and surface ``queued=False`` so the caller
    # can decide whether to retry.
    queued = False
    try:
        from platform.infrastructure.celery_app import app

        app.send_task(
            "platform.tasks.run_backtest",
            args=[str(backtest_id)],
            queue="backtest",
        )
        queued = True
    except Exception:  # noqa: BLE001 — Celery may not be running in dev
        _log.warning(
            "backtest_enqueue_failed",
            backtest_id=str(backtest_id),
            reason="celery_unreachable",
        )

    await get_event_bus().publish(
        Topic.AUDIT,
        {
            "type": "backtest_queued",
            "org_id": str(cmd.org_id),
            "backtest_id": str(backtest_id),
            "strategy_id": str(cmd.strategy_id),
            "symbol": cmd.symbol,
            "timeframe": cmd.timeframe,
            "queued": queued,
            "actor_id": str(cmd.user_id),
        },
    )
    _log.info(
        "backtest_queued",
        backtest_id=str(backtest_id),
        strategy_id=str(cmd.strategy_id),
        symbol=cmd.symbol,
        queued=queued,
    )
    return RunBacktestResult(backtest_id=backtest_id, status="pending", queued=queued)
