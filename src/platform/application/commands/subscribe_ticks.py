"""Subscribe a terminal to tick updates for a list of symbols.

Vertical slice:

  API → command → bridge.subscribe_ticks → record subscription in Terminal.symbols
        → publish TERMINAL_EVENTS event

The bridge client forwards the ``SUBSCRIBE_TICKS`` command to the terminal;
the terminal then starts streaming ticks for the requested symbols (see
``Topic.TICKS`` subscribers for the ingestion path).
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

from platform.core.exceptions import NotFoundError, ValidationError
from platform.core.logging import get_logger
from platform.db.models import Terminal
from platform.db.session import db_context
from platform.events.bus import get_event_bus
from platform.events.topics import Topic
from platform.infrastructure.mt5_bridge.client import get_bridge_client

_log = get_logger(__name__)


# ── Command + DTO ──────────────────────────────────────────────────────────


class SubscribeTicksCommand(BaseModel):
    org_id: UUID
    user_id: UUID
    terminal_id: str  # external
    symbols: list[str]


class SubscribeTicksResult(BaseModel):
    terminal_id: str
    subscribed: list[str]
    already_subscribed: list[str]
    total_symbols: int


# ── Handler ─────────────────────────────────────────────────────────────────


async def handle_subscribe_ticks(cmd: SubscribeTicksCommand) -> SubscribeTicksResult:
    """Forward the subscription request to the bridge and record it on the Terminal."""
    if not cmd.symbols:
        raise ValidationError("symbols list must not be empty")
    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique_symbols: list[str] = []
    for s in cmd.symbols:
        if s not in seen:
            seen.add(s)
            unique_symbols.append(s)

    bridge = get_bridge_client()
    reply = await bridge.subscribe_ticks(
        terminal_id=cmd.terminal_id, symbols=unique_symbols, timeout=5.0
    )
    # Bridge may echo the accepted symbol list — use it if present.
    accepted: list[str] = list(reply.payload.get("symbols", unique_symbols) or unique_symbols)

    already: list[str] = []
    async with db_context() as db:
        terminal = (
            await db.execute(
                select(Terminal).where(
                    Terminal.terminal_id == cmd.terminal_id, Terminal.org_id == cmd.org_id
                )
            )
        ).scalar_one_or_none()
        if terminal is None:
            raise NotFoundError(f"Terminal {cmd.terminal_id} not found")

        current: list[str] = list(terminal.symbols or [])
        current_set = set(current)
        newly_added: list[str] = []
        for sym in accepted:
            if sym in current_set:
                already.append(sym)
            else:
                current.append(sym)
                current_set.add(sym)
                newly_added.append(sym)
        terminal.symbols = current
        terminal.updated_at = datetime.now(timezone.utc)
        await db.commit()

    await get_event_bus().publish(
        Topic.TERMINAL_EVENTS,
        {
            "type": "ticks_subscribed",
            "org_id": str(cmd.org_id),
            "terminal_id": cmd.terminal_id,
            "symbols": accepted,
            "newly_added": newly_added,
            "already_subscribed": already,
            "actor_id": str(cmd.user_id),
        },
    )
    _log.info(
        "ticks_subscribed",
        terminal_id=cmd.terminal_id,
        count=len(accepted),
        new=len(newly_added),
    )
    return SubscribeTicksResult(
        terminal_id=cmd.terminal_id,
        subscribed=newly_added,
        already_subscribed=already,
        total_symbols=len(accepted),
    )
