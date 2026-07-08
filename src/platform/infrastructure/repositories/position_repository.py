"""PositionRepository — persistence for the Position aggregate.

Converts between `PositionModel` rows and the domain `Position` aggregate (which
uses `Price` / `Quantity` value objects). The ORM has two columns the aggregate
lacks (`broker_position_id`, `unrealized_pnl`) and one NOT NULL column
(`current_price`) the aggregate treats as optional — handled via `getattr`
fallbacks on save.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from platform.db.models import Position as PositionModel
from platform.domain.shared import Price, Quantity
from platform.domain.trading import Position, PositionStatus, OrderSide


class PositionRepository:
    """Async repository for the Position aggregate."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Conversions ─────────────────────────────────────────────────────────

    @staticmethod
    def to_domain(m: PositionModel) -> Position:
        pos = Position(
            id=m.id, org_id=m.org_id, terminal_id=m.terminal_id, symbol=m.symbol,
            side=OrderSide(m.side), volume=Quantity(volume=float(m.volume)),
            open_price=Price(value=float(m.open_price)), opened_at=m.opened_at,
            stop_loss=Price(value=float(m.stop_loss)) if m.stop_loss is not None else None,
            take_profit=Price(value=float(m.take_profit)) if m.take_profit is not None else None,
            current_price=Price(value=float(m.current_price)) if m.current_price else None,
            swap=float(m.swap or 0), realized_pnl=float(m.realized_pnl or 0),
            status=PositionStatus(m.status), closed_at=m.closed_at,
        )
        # Side-channel ORM-only fields so save() can write them back.
        pos.broker_position_id = m.broker_position_id  # type: ignore[attr-defined]
        pos.strategy_id = getattr(m, "strategy_id", None)  # type: ignore[attr-defined]
        return pos

    @staticmethod
    def from_domain(e: Position) -> PositionModel:
        current = e.current_price.value if e.current_price is not None else e.open_price.value
        return PositionModel(
            id=e.id, org_id=e.org_id, terminal_id=e.terminal_id,
            broker_position_id=getattr(e, "broker_position_id", None),
            symbol=e.symbol, side=e.side.value, volume=e.volume.volume,
            open_price=e.open_price.value, current_price=current,
            stop_loss=e.stop_loss.value if e.stop_loss is not None else None,
            take_profit=e.take_profit.value if e.take_profit is not None else None,
            swap=e.swap, unrealized_pnl=e.unrealized_pnl, realized_pnl=e.realized_pnl,
            opened_at=e.opened_at, closed_at=e.closed_at, status=e.status.value,
        )

    # ── Reads ───────────────────────────────────────────────────────────────

    async def get(self, id: UUID) -> Position | None:
        m = await self.db.get(PositionModel, id)
        return self.to_domain(m) if m else None

    async def get_by_broker_position_id(
        self, terminal_id: UUID, broker_position_id: str,
    ) -> Position | None:
        stmt = select(PositionModel).where(
            PositionModel.terminal_id == terminal_id,
            PositionModel.broker_position_id == broker_position_id,
        )
        m = (await self.db.execute(stmt)).scalar_one_or_none()
        return self.to_domain(m) if m else None

    async def list_by_org(
        self, org_id: UUID, *, status: str | None = None, limit: int = 200,
    ) -> list[Position]:
        stmt = select(PositionModel).where(PositionModel.org_id == org_id)
        if status:
            stmt = stmt.where(PositionModel.status == status)
        stmt = stmt.order_by(PositionModel.opened_at.desc()).limit(limit)
        return [self.to_domain(r) for r in (await self.db.execute(stmt)).scalars().all()]

    async def list_open_by_terminal(self, terminal_id: UUID) -> list[Position]:
        stmt = select(PositionModel).where(
            PositionModel.terminal_id == terminal_id,
            PositionModel.status == PositionStatus.OPEN.value,
        ).order_by(PositionModel.opened_at.desc())
        return [self.to_domain(r) for r in (await self.db.execute(stmt)).scalars().all()]

    # ── Writes ──────────────────────────────────────────────────────────────

    async def add(self, entity: Position) -> Position:
        self.db.add(self.from_domain(entity))
        await self.db.flush()
        return entity

    async def save(self, entity: Position) -> Position:
        m = await self.db.get(PositionModel, entity.id)
        if m is None:
            return await self.add(entity)
        m.current_price = (
            entity.current_price.value if entity.current_price is not None else m.current_price
        )
        m.stop_loss = entity.stop_loss.value if entity.stop_loss is not None else None
        m.take_profit = entity.take_profit.value if entity.take_profit is not None else None
        m.swap = entity.swap
        m.unrealized_pnl = entity.unrealized_pnl
        m.realized_pnl = entity.realized_pnl
        m.status = entity.status.value
        m.closed_at = entity.closed_at
        m.broker_position_id = getattr(entity, "broker_position_id", None)
        await self.db.flush()
        return entity

    async def close_position(
        self, id: UUID, close_price: float, realized_pnl: float,
    ) -> bool:
        now = datetime.now(timezone.utc)
        stmt = update(PositionModel).where(
            PositionModel.id == id, PositionModel.status == PositionStatus.OPEN.value,
        ).values(
            current_price=close_price, realized_pnl=realized_pnl,
            status=PositionStatus.CLOSED.value, closed_at=now, updated_at=now,
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return (result.rowcount or 0) > 0

    async def mark_to_market(
        self, id: UUID, current_price: float, unrealized_pnl: float,
    ) -> bool:
        stmt = update(PositionModel).where(
            PositionModel.id == id, PositionModel.status == PositionStatus.OPEN.value,
        ).values(
            current_price=current_price, unrealized_pnl=unrealized_pnl,
            updated_at=datetime.now(timezone.utc),
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return (result.rowcount or 0) > 0
