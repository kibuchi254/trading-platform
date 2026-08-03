"""Positions REST router — list / detail / close / modify.

Wraps the application commands `close_position` and `modify_position` and the
`list_positions` query. Org-scoped via the authenticated user.
"""

from __future__ import annotations

from platform.application.commands.close_position import (
    ClosePositionCommand,
    handle_close_position,
)
from platform.application.commands.modify_position import (
    ModifyPositionCommand,
    handle_modify_position,
)
from platform.application.queries.list_positions import (
    ListPositionsQuery,
    handle_list_positions,
)
from platform.core.dependencies import CurrentUser, get_current_user
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

router = APIRouter(prefix="/positions", tags=["positions"])


class ModifyPositionRequest(BaseModel):
    stop_loss: float | None = None
    take_profit: float | None = None


class ClosePositionRequest(BaseModel):
    volume: float | None = None  # None = full close


@router.get("")
async def list_positions(
    user: CurrentUser = Depends(get_current_user),
    status: str = Query(default="all"),
    limit: int = Query(default=200, le=1000),
) -> dict:
    result = await handle_list_positions(
        ListPositionsQuery(org_id=user.org_id, status=status, limit=limit)
    )
    return result.model_dump(mode="json")


@router.get("/{position_id}")
async def get_position(
    position_id: UUID,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    # Reuse the list query filtered to a single id by listing then matching —
    # a dedicated get handler can be added if hot-path latency demands it.
    from platform.db.models import Position
    from platform.db.session import db_context

    async with db_context() as db:
        pos = await db.get(Position, position_id)
        if pos is None or pos.org_id != user.org_id:
            from platform.core.exceptions import NotFoundError

            raise NotFoundError(f"Position {position_id} not found")
        return {
            "id": str(pos.id),
            "terminal_id": str(pos.terminal_id),
            "broker_position_id": pos.broker_position_id,
            "symbol": pos.symbol,
            "side": pos.side,
            "volume": float(pos.volume or 0),
            "open_price": float(pos.open_price or 0),
            "current_price": float(pos.current_price or 0),
            "stop_loss": float(pos.stop_loss) if pos.stop_loss is not None else None,
            "take_profit": float(pos.take_profit) if pos.take_profit is not None else None,
            "swap": float(pos.swap or 0),
            "unrealized_pnl": float(pos.unrealized_pnl or 0),
            "realized_pnl": float(pos.realized_pnl or 0),
            "status": pos.status,
            "opened_at": pos.opened_at.isoformat() if pos.opened_at else None,
            "closed_at": pos.closed_at.isoformat() if pos.closed_at else None,
        }


@router.post("/{position_id}/close")
async def close_position(
    position_id: UUID,
    req: ClosePositionRequest,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    result = await handle_close_position(
        ClosePositionCommand(
            org_id=user.org_id,
            user_id=user.user_id,
            position_id=position_id,
            volume=req.volume,
        )
    )
    return result.model_dump(mode="json")


@router.post("/{position_id}/modify")
async def modify_position(
    position_id: UUID,
    req: ModifyPositionRequest,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    result = await handle_modify_position(
        ModifyPositionCommand(
            org_id=user.org_id,
            user_id=user.user_id,
            position_id=position_id,
            stop_loss=req.stop_loss,
            take_profit=req.take_profit,
        )
    )
    return result.model_dump(mode="json")
