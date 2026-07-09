"""Close a position (fully or partially).

Vertical slice:

  API → command → load Position row → resolve external terminal_id
        → bridge.close_position → mark Position closed
        → write Trade row (realized PnL, duration)
        → publish POSITION_UPDATES event
"""

from __future__ import annotations

from datetime import UTC, datetime
from platform.core.exceptions import NotFoundError, ValidationError
from platform.core.logging import get_logger
from platform.db.models import Position, Terminal, Trade
from platform.db.session import db_context
from platform.events.bus import get_event_bus
from platform.events.topics import Topic
from platform.infrastructure.mt5_bridge.client import get_bridge_client
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

_log = get_logger(__name__)


# ── Command + DTO ──────────────────────────────────────────────────────────


class ClosePositionCommand(BaseModel):
    org_id: UUID
    user_id: UUID
    position_id: UUID
    volume: float | None = None  # None = full close


class ClosePositionResult(BaseModel):
    position_id: UUID
    status: str
    realized_pnl: float | None = None
    closed_volume: float | None = None
    close_price: float | None = None
    trade_id: UUID | None = None


# ── Handler ─────────────────────────────────────────────────────────────────


async def handle_close_position(cmd: ClosePositionCommand) -> ClosePositionResult:
    """Close the position via the bridge, then persist Position + Trade."""
    if cmd.volume is not None and cmd.volume <= 0:
        raise ValidationError("Close volume must be positive")

    async with db_context() as db:
        pos = await db.get(Position, cmd.position_id)
        if pos is None or pos.org_id != cmd.org_id:
            raise NotFoundError(f"Position {cmd.position_id} not found")
        if pos.status != "open":
            raise ValidationError(f"Position already in status {pos.status}")
        if not pos.broker_position_id:
            raise ValidationError("Position has no broker_position_id")

        # Resolve external terminal_id from the internal FK.
        terminal = (
            await db.execute(select(Terminal).where(Terminal.id == pos.terminal_id))
        ).scalar_one_or_none()
        if terminal is None:
            raise NotFoundError("Terminal for position not found")

        bridge = get_bridge_client()
        reply = await bridge.close_position(
            terminal_id=terminal.terminal_id,
            broker_position_id=pos.broker_position_id,
            volume=cmd.volume,
        )

        remote_status = reply.payload.get("status", "closed")
        close_price = float(
            reply.payload.get("price") or reply.payload.get("avg_price") or pos.current_price
        )
        closed_volume = float(reply.payload.get("volume") or pos.volume)
        realized_pnl = float(reply.payload.get("pnl") or pos.unrealized_pnl or 0)

        trade_id: UUID | None = None
        now = datetime.now(UTC)
        if remote_status in ("closed", "filled"):
            pos.status = "closed"
            pos.closed_at = now
            pos.realized_pnl = realized_pnl
            pos.current_price = close_price

            duration = max(0, int((now - pos.opened_at).total_seconds())) if pos.opened_at else 0
            pips = _pips(pos.symbol, pos.open_price, close_price, pos.side)
            trade = Trade(
                org_id=pos.org_id,
                position_id=pos.id,
                symbol=pos.symbol,
                side=pos.side,
                volume=closed_volume,
                entry_price=pos.open_price,
                exit_price=close_price,
                pnl=realized_pnl,
                pips=pips,
                commission=float(reply.payload.get("commission", 0) or 0),
                swap=float(pos.swap or 0),
                duration_seconds=duration,
                opened_at=pos.opened_at,
                closed_at=now,
            )
            db.add(trade)
            await db.flush()
            trade_id = trade.id

        await db.commit()

        result = ClosePositionResult(
            position_id=pos.id,
            status=pos.status,
            realized_pnl=float(pos.realized_pnl) if pos.realized_pnl else realized_pnl,
            closed_volume=closed_volume,
            close_price=close_price,
            trade_id=trade_id,
        )

    await get_event_bus().publish(
        Topic.POSITION_UPDATES,
        {
            "type": "position_closed",
            "org_id": str(cmd.org_id),
            "position_id": str(result.position_id),
            "status": result.status,
            "realized_pnl": result.realized_pnl,
            "closed_volume": result.closed_volume,
            "close_price": result.close_price,
            "trade_id": str(result.trade_id) if result.trade_id else None,
            "actor_id": str(cmd.user_id),
        },
    )
    _log.info(
        "position_closed",
        position_id=str(result.position_id),
        realized_pnl=result.realized_pnl,
    )
    return result


def _pips(symbol: str, entry: float, exit_: float, side: str) -> float:
    """Rough pip calculation. 5-digit FX → pip = 0.0001; JPY pairs → 0.01;
    everything else falls back to price difference (indices/metals/crypto)."""
    if not entry:
        return 0.0
    diff = (exit_ - entry) if side == "buy" else (entry - exit_)
    if symbol.upper().endswith("JPY"):
        return round(diff / 0.01, 2)
    if len(symbol) >= 6 and symbol.upper()[:3] in {"EUR", "GBP", "USD", "AUD", "NZD", "CHF", "CAD"}:
        return round(diff / 0.0001, 2)
    return round(diff, 5)
