"""Activate a strategy on a terminal — wire bar-close subscriptions.

Vertical slice:

  API → command → load Strategy → flip is_active=True
        → persist terminal + symbols + timeframes onto the strategy config
        → subscribe the terminal to bar-close events for the strategy's symbols
        → publish SIGNALS event (strategy_activated)

This is the runtime "go live" path: the strategy has already been registered
(via :mod:`platform.application.commands.register_strategy`); activation
binds it to a specific terminal and asks the bridge to start streaming the
relevant OHLC bars.
"""

from __future__ import annotations

from datetime import UTC, datetime
from platform.core.exceptions import NotFoundError, ValidationError
from platform.core.logging import get_logger
from platform.db.models import Strategy as StrategyModel
from platform.db.models import Terminal
from platform.db.session import db_context
from platform.events.bus import get_event_bus
from platform.events.topics import Topic
from platform.infrastructure.mt5_bridge.client import get_bridge_client
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

_log = get_logger(__name__)


# ── Command + DTO ──────────────────────────────────────────────────────────


class ActivateStrategyCommand(BaseModel):
    strategy_id: UUID
    org_id: UUID
    terminal_id: str  # external
    symbols: list[str]
    timeframes: list[str] = ["M15"]


class ActivateStrategyResult(BaseModel):
    strategy_id: UUID
    terminal_id: str
    is_active: bool
    symbols: list[str]
    timeframes: list[str]
    activated_at: str


# ── Handler ─────────────────────────────────────────────────────────────────


async def handle_activate_strategy(cmd: ActivateStrategyCommand) -> ActivateStrategyResult:
    """Flip ``is_active`` and ask the bridge to subscribe to the strategy's bars."""
    if not cmd.symbols:
        raise ValidationError("symbols must not be empty")
    if not cmd.timeframes:
        raise ValidationError("timeframes must not be empty")

    async with db_context() as db:
        strategy = await db.get(StrategyModel, cmd.strategy_id)
        if strategy is None or strategy.org_id != cmd.org_id:
            raise NotFoundError(f"Strategy {cmd.strategy_id} not found")

        terminal = (
            await db.execute(
                select(Terminal).where(
                    Terminal.terminal_id == cmd.terminal_id, Terminal.org_id == cmd.org_id
                )
            )
        ).scalar_one_or_none()
        if terminal is None:
            raise NotFoundError(f"Terminal {cmd.terminal_id} not found")

        strategy.is_active = True
        # Stash the activation context (terminal + symbols + timeframes) inside
        # the strategy config so the strategy runner knows where to look. The
        # Strategy ORM does not have dedicated columns for these — config JSONB
        # is the intended extension point.
        config = dict(strategy.config or {})
        config["activation"] = {
            "terminal_id": cmd.terminal_id,
            "symbols": cmd.symbols,
            "timeframes": cmd.timeframes,
            "activated_at": datetime.now(UTC).isoformat(),
        }
        strategy.config = config
        strategy.updated_at = datetime.now(UTC)
        await db.commit()

    # Subscribe the terminal to ticks for each strategy symbol — the
    # market-data engine turns those ticks into OHLC bars and emits BAR events
    # which the strategy runner subscribes to.
    bridge = get_bridge_client()
    try:
        await bridge.subscribe_ticks(terminal_id=cmd.terminal_id, symbols=cmd.symbols, timeout=5.0)
    except Exception as e:
        _log.warning(
            "activate_strategy_subscribe_failed",
            strategy_id=str(cmd.strategy_id),
            terminal_id=cmd.terminal_id,
            error=str(e),
        )

    now_iso = datetime.now(UTC).isoformat()
    await get_event_bus().publish(
        Topic.SIGNALS,
        {
            "type": "strategy_activated",
            "org_id": str(cmd.org_id),
            "strategy_id": str(cmd.strategy_id),
            "terminal_id": cmd.terminal_id,
            "symbols": cmd.symbols,
            "timeframes": cmd.timeframes,
            "activated_at": now_iso,
        },
    )
    _log.info(
        "strategy_activated",
        strategy_id=str(cmd.strategy_id),
        terminal_id=cmd.terminal_id,
        symbols=cmd.symbols,
        timeframes=cmd.timeframes,
    )
    return ActivateStrategyResult(
        strategy_id=cmd.strategy_id,
        terminal_id=cmd.terminal_id,
        is_active=True,
        symbols=cmd.symbols,
        timeframes=cmd.timeframes,
        activated_at=now_iso,
    )
