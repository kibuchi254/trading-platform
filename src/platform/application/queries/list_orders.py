"""List orders for an org with optional filters.

Vertical slice:

  API → query → DB: select Order rows by org_id (+ optional filters)
        → return paginated DTOs

The application layer reads ORM models directly — no repository indirection
is needed for read-only queries (per the project convention noted in
``platform.application.commands.place_order``).
"""

from __future__ import annotations

from datetime import datetime
from platform.db.models import Order as OrderModel
from platform.db.session import db_context
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

# ── Query + DTO ────────────────────────────────────────────────────────────


class ListOrdersQuery(BaseModel):
    org_id: UUID
    status: str | None = None
    terminal_id: UUID | None = None  # internal terminal id
    symbol: str | None = None
    limit: int = 100


class OrderSummary(BaseModel):
    id: UUID
    client_order_id: str
    broker_order_id: str | None
    terminal_id: UUID
    strategy_id: UUID | None
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
    created_at: datetime
    filled_at: datetime | None


class ListOrdersResult(BaseModel):
    orders: list[OrderSummary]
    total: int


# ── Handler ─────────────────────────────────────────────────────────────────


async def handle_list_orders(query: ListOrdersQuery) -> ListOrdersResult:
    """Filter and paginate orders for the org."""
    # Clamp limit to a reasonable ceiling to avoid accidental huge pulls.
    limit = max(1, min(query.limit, 500))

    async with db_context() as db:
        stmt = select(OrderModel).where(OrderModel.org_id == query.org_id)
        if query.status is not None:
            stmt = stmt.where(OrderModel.status == query.status)
        if query.terminal_id is not None:
            stmt = stmt.where(OrderModel.terminal_id == query.terminal_id)
        if query.symbol is not None:
            stmt = stmt.where(OrderModel.symbol == query.symbol)
        stmt = stmt.order_by(OrderModel.created_at.desc()).limit(limit)
        rows = (await db.execute(stmt)).scalars().all()

    orders = [
        OrderSummary(
            id=r.id,
            client_order_id=r.client_order_id,
            broker_order_id=r.broker_order_id,
            terminal_id=r.terminal_id,
            strategy_id=r.strategy_id,
            symbol=r.symbol,
            side=r.side,
            order_type=r.order_type,
            volume=float(r.volume or 0),
            price=float(r.price) if r.price is not None else None,
            stop_loss=float(r.stop_loss) if r.stop_loss is not None else None,
            take_profit=float(r.take_profit) if r.take_profit is not None else None,
            status=r.status,
            filled_volume=float(r.filled_volume or 0),
            avg_fill_price=float(r.avg_fill_price) if r.avg_fill_price is not None else None,
            rejection_reason=r.rejection_reason,
            created_at=r.created_at,
            filled_at=r.filled_at,
        )
        for r in rows
    ]
    return ListOrdersResult(orders=orders, total=len(orders))
