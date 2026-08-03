"""Signals REST router — recent strategy / AI signal feed.

Wraps the `list_signals` query. Org-scoped via the authenticated user.
"""

from __future__ import annotations

from platform.application.queries.list_signals import ListSignalsQuery, handle_list_signals
from platform.core.dependencies import CurrentUser, get_current_user
from uuid import UUID

from fastapi import APIRouter, Depends, Query

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("")
async def list_signals(
    user: CurrentUser = Depends(get_current_user),
    symbol: str | None = Query(default=None),
    strategy_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, le=500),
) -> dict:
    result = await handle_list_signals(
        ListSignalsQuery(
            org_id=user.org_id,
            symbol=symbol,
            strategy_id=strategy_id,
            limit=limit,
        )
    )
    return result.model_dump(mode="json")
