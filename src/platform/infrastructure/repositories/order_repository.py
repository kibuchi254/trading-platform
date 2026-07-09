"""OrderRepository — persistence for the Order aggregate.

Converts between `OrderModel` rows and the domain `Order` aggregate (which uses
`Price` / `Quantity` value objects and the `OrderSide` / `OrderType` /
`OrderStatus` enums). The repository is the only place SQLAlchemy touches an
Order — application + domain layers depend on the aggregate alone.
"""

from __future__ import annotations

from datetime import UTC, datetime
from platform.db.models import Order as OrderModel
from platform.domain.shared import Price, Quantity
from platform.domain.trading import Order, OrderSide, OrderStatus, OrderType
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


class OrderRepository:
    """Async repository for the Order aggregate."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Conversions ─────────────────────────────────────────────────────────

    @staticmethod
    def to_domain(m: OrderModel) -> Order:
        order = Order(
            id=m.id,
            org_id=m.org_id,
            terminal_id=m.terminal_id,
            client_order_id=m.client_order_id,
            symbol=m.symbol,
            side=OrderSide(m.side),
            order_type=OrderType(m.order_type),
            volume=Quantity(volume=float(m.volume)),
            price=Price(value=float(m.price)) if m.price is not None else None,
            stop_loss=Price(value=float(m.stop_loss)) if m.stop_loss is not None else None,
            take_profit=Price(value=float(m.take_profit)) if m.take_profit is not None else None,
            status=OrderStatus(m.status),
            filled_volume=float(m.filled_volume or 0),
            avg_fill_price=float(m.avg_fill_price) if m.avg_fill_price is not None else None,
            strategy_id=m.strategy_id,
            rejection_reason=m.rejection_reason,
            created_at=m.created_at,
            submitted_at=m.submitted_at,
            filled_at=m.filled_at,
        )
        # Side-channel ORM-only fields so save() can write them back.
        order.broker_order_id = m.broker_order_id  # type: ignore[attr-defined]
        order.signal_id = m.signal_id  # type: ignore[attr-defined]
        return order

    @staticmethod
    def from_domain(e: Order) -> OrderModel:
        return OrderModel(
            id=e.id,
            org_id=e.org_id,
            terminal_id=e.terminal_id,
            strategy_id=e.strategy_id,
            signal_id=getattr(e, "signal_id", None),
            client_order_id=e.client_order_id,
            broker_order_id=getattr(e, "broker_order_id", None),
            symbol=e.symbol,
            side=e.side.value,
            order_type=e.order_type.value,
            volume=e.volume.volume,
            price=e.price.value if e.price is not None else None,
            stop_loss=e.stop_loss.value if e.stop_loss is not None else None,
            take_profit=e.take_profit.value if e.take_profit is not None else None,
            status=e.status.value,
            filled_volume=e.filled_volume,
            avg_fill_price=e.avg_fill_price,
            rejection_reason=e.rejection_reason,
            submitted_at=e.submitted_at,
            filled_at=e.filled_at,
        )

    # ── Reads ───────────────────────────────────────────────────────────────

    async def get(self, id: UUID) -> Order | None:
        m = await self.db.get(OrderModel, id)
        return self.to_domain(m) if m else None

    async def get_by_client_order_id(self, client_order_id: str) -> Order | None:
        stmt = select(OrderModel).where(OrderModel.client_order_id == client_order_id)
        m = (await self.db.execute(stmt)).scalar_one_or_none()
        return self.to_domain(m) if m else None

    async def list_by_org(
        self,
        org_id: UUID,
        *,
        status: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Order]:
        stmt = select(OrderModel).where(OrderModel.org_id == org_id)
        if status:
            stmt = stmt.where(OrderModel.status == status)
        if symbol:
            stmt = stmt.where(OrderModel.symbol == symbol)
        stmt = stmt.order_by(OrderModel.created_at.desc()).limit(limit).offset(offset)
        return [self.to_domain(r) for r in (await self.db.execute(stmt)).scalars().all()]

    async def list_by_terminal(
        self,
        terminal_id: UUID,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[Order]:
        stmt = select(OrderModel).where(OrderModel.terminal_id == terminal_id)
        if status:
            stmt = stmt.where(OrderModel.status == status)
        stmt = stmt.order_by(OrderModel.created_at.desc()).limit(limit)
        return [self.to_domain(r) for r in (await self.db.execute(stmt)).scalars().all()]

    async def list_by_status(self, org_id: UUID, status: str) -> list[Order]:
        stmt = (
            select(OrderModel)
            .where(
                OrderModel.org_id == org_id,
                OrderModel.status == status,
            )
            .order_by(OrderModel.created_at.desc())
        )
        return [self.to_domain(r) for r in (await self.db.execute(stmt)).scalars().all()]

    async def add(self, entity: Order) -> Order:
        self.db.add(self.from_domain(entity))
        await self.db.flush()
        return entity

    async def save(self, entity: Order) -> Order:
        m = await self.db.get(OrderModel, entity.id)
        if m is None:
            return await self.add(entity)
        m.broker_order_id = getattr(entity, "broker_order_id", None)
        m.signal_id = getattr(entity, "signal_id", None)
        m.status = entity.status.value
        m.filled_volume = entity.filled_volume
        m.avg_fill_price = entity.avg_fill_price
        m.rejection_reason = entity.rejection_reason
        m.submitted_at = entity.submitted_at
        m.filled_at = entity.filled_at
        await self.db.flush()
        return entity

    async def update_status(
        self,
        id: UUID,
        status: str,
        *,
        rejection_reason: str | None = None,
    ) -> bool:
        values: dict = {"status": status, "updated_at": datetime.now(UTC)}
        if rejection_reason is not None:
            values["rejection_reason"] = rejection_reason
        stmt = update(OrderModel).where(OrderModel.id == id).values(**values)
        result = await self.db.execute(stmt)
        await self.db.flush()
        return (result.rowcount or 0) > 0

    async def update_fill(
        self,
        id: UUID,
        *,
        filled_volume: float,
        avg_fill_price: float | None,
        status: str,
        broker_order_id: str | None = None,
    ) -> bool:
        now = datetime.now(UTC)
        values: dict = {
            "filled_volume": filled_volume,
            "avg_fill_price": avg_fill_price,
            "status": status,
            "filled_at": now if status == "filled" else None,
            "updated_at": now,
        }
        if broker_order_id is not None:
            values["broker_order_id"] = broker_order_id
        stmt = update(OrderModel).where(OrderModel.id == id).values(**values)
        result = await self.db.execute(stmt)
        await self.db.flush()
        return (result.rowcount or 0) > 0
