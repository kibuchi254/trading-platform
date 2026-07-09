"""Orders REST router — place / list / detail / cancel."""

from __future__ import annotations

from platform.application.commands.place_order import (
    PlaceOrderCommand,
    PlaceOrderResult,
    handle_place_order,
)
from platform.core.dependencies import CurrentUser, get_current_user
from platform.db.models import Order as OrderModel
from platform.db.session import get_db
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/orders", tags=["orders"])


class PlaceOrderRequest(BaseModel):
    terminal_id: str
    symbol: str
    side: str  # buy | sell
    order_type: str = "market"  # market | limit | stop | stop_limit
    volume: float = Field(gt=0)
    price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    strategy_id: UUID | None = None
    comment: str | None = None
    magic: int | None = None


class OrderOut(BaseModel):
    id: UUID
    client_order_id: str
    broker_order_id: str | None
    terminal_id: UUID
    symbol: str
    side: str
    order_type: str
    volume: float
    price: float | None
    stop_loss: float | None
    take_profit: float | None
    status: str
    filled_volume: float
    avg_fill_price: float | None
    rejection_reason: str | None
    created_at: str

    model_config = {"from_attributes": True}


@router.post("", response_model=PlaceOrderResult, status_code=201)
async def place_order(
    req: PlaceOrderRequest,
    user: CurrentUser = Depends(get_current_user),
) -> PlaceOrderResult:
    cmd = PlaceOrderCommand(
        org_id=user.org_id,
        user_id=user.user_id,
        **req.model_dump(),
    )
    return await handle_place_order(cmd)


@router.get("", response_model=list[OrderOut])
async def list_orders(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, le=500),
) -> list[OrderOut]:
    stmt = select(OrderModel).where(OrderModel.org_id == user.org_id)
    if status_filter:
        stmt = stmt.where(OrderModel.status == status_filter)
    stmt = stmt.order_by(OrderModel.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        OrderOut(
            id=r.id,
            client_order_id=r.client_order_id,
            broker_order_id=r.broker_order_id,
            terminal_id=r.terminal_id,
            symbol=r.symbol,
            side=r.side,
            order_type=r.order_type,
            volume=float(r.volume),
            price=float(r.price) if r.price else None,
            stop_loss=float(r.stop_loss) if r.stop_loss else None,
            take_profit=float(r.take_profit) if r.take_profit else None,
            status=r.status,
            filled_volume=float(r.filled_volume),
            avg_fill_price=float(r.avg_fill_price) if r.avg_fill_price else None,
            rejection_reason=r.rejection_reason,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(
    order_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderOut:
    r = await db.get(OrderModel, order_id)
    if r is None or r.org_id != user.org_id:
        from platform.core.exceptions import NotFoundError

        raise NotFoundError(f"Order {order_id} not found")
    return OrderOut(
        id=r.id,
        client_order_id=r.client_order_id,
        broker_order_id=r.broker_order_id,
        terminal_id=r.terminal_id,
        symbol=r.symbol,
        side=r.side,
        order_type=r.order_type,
        volume=float(r.volume),
        price=float(r.price) if r.price else None,
        stop_loss=float(r.stop_loss) if r.stop_loss else None,
        take_profit=float(r.take_profit) if r.take_profit else None,
        status=r.status,
        filled_volume=float(r.filled_volume),
        avg_fill_price=float(r.avg_fill_price) if r.avg_fill_price else None,
        rejection_reason=r.rejection_reason,
        created_at=r.created_at.isoformat(),
    )
