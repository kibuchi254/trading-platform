"""StrategyRepository — persistence for the Strategy aggregate.

Converts between the SQLAlchemy `StrategyModel` row and the domain `Strategy`
aggregate. The aggregate owns its lifecycle (activate / deactivate) and its
config version; this repository is the only place SQLAlchemy touches a
Strategy.
"""

from __future__ import annotations

from datetime import UTC, datetime
from platform.db.models import Strategy as StrategyModel
from platform.domain.strategy import Strategy, StrategyConfig
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


class StrategyRepository:
    """Async repository for the Strategy aggregate."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Conversions ─────────────────────────────────────────────────────────

    @staticmethod
    def to_domain(m: StrategyModel) -> Strategy:
        config = m.config or {}
        return Strategy(
            id=m.id,
            org_id=m.org_id,
            name=m.name,
            slug=m.slug,
            kind=m.kind,
            version=m.version or "1.0.0",
            config=StrategyConfig(
                version=m.version or "1.0.0",
                params=config.get("params", {}) if isinstance(config, dict) else {},
                risk_overrides=config.get("risk_overrides", {}) if isinstance(config, dict) else {},
            ),
            is_active=bool(m.is_active),
            description=m.description or "",
            created_at=m.created_at,
        )

    @staticmethod
    def from_domain(e: Strategy) -> StrategyModel:
        return StrategyModel(
            id=e.id,
            org_id=e.org_id,
            name=e.name,
            slug=e.slug,
            kind=e.kind,
            version=e.version,
            config={
                "version": e.config.version,
                "params": e.config.params,
                "risk_overrides": e.config.risk_overrides,
            },
            is_active=e.is_active,
            description=e.description,
        )

    # ── Reads ───────────────────────────────────────────────────────────────

    async def get(self, id: UUID) -> Strategy | None:
        m = await self.db.get(StrategyModel, id)
        if m is None or m.deleted_at is not None:
            return None
        return self.to_domain(m)

    async def get_by_slug(self, org_id: UUID, slug: str) -> Strategy | None:
        stmt = select(StrategyModel).where(
            StrategyModel.org_id == org_id,
            StrategyModel.slug == slug,
            StrategyModel.deleted_at.is_(None),
        )
        m = (await self.db.execute(stmt)).scalar_one_or_none()
        return self.to_domain(m) if m else None

    async def list_by_org(
        self,
        org_id: UUID,
        *,
        active_only: bool = False,
        limit: int = 200,
    ) -> list[Strategy]:
        stmt = select(StrategyModel).where(
            StrategyModel.org_id == org_id,
            StrategyModel.deleted_at.is_(None),
        )
        if active_only:
            stmt = stmt.where(StrategyModel.is_active.is_(True))
        stmt = stmt.order_by(StrategyModel.created_at.desc()).limit(limit)
        rows = (await self.db.execute(stmt)).scalars().all()
        return [self.to_domain(r) for r in rows]

    async def list_active_by_org(self, org_id: UUID) -> list[Strategy]:
        return await self.list_by_org(org_id, active_only=True)

    # ── Writes ──────────────────────────────────────────────────────────────

    async def add(self, entity: Strategy) -> Strategy:
        self.db.add(self.from_domain(entity))
        await self.db.flush()
        return entity

    async def save(self, entity: Strategy) -> Strategy:
        m = await self.db.get(StrategyModel, entity.id)
        if m is None:
            return await self.add(entity)
        m.name = entity.name
        m.slug = entity.slug
        m.kind = entity.kind
        m.version = entity.version
        m.config = {
            "version": entity.config.version,
            "params": entity.config.params,
            "risk_overrides": entity.config.risk_overrides,
        }
        m.is_active = entity.is_active
        m.description = entity.description
        await self.db.flush()
        return entity

    async def activate(self, id: UUID) -> bool:
        stmt = (
            update(StrategyModel)
            .where(
                StrategyModel.id == id,
                StrategyModel.deleted_at.is_(None),
            )
            .values(
                is_active=True,
                updated_at=datetime.now(UTC),
            )
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return (result.rowcount or 0) > 0

    async def deactivate(self, id: UUID) -> bool:
        stmt = (
            update(StrategyModel)
            .where(
                StrategyModel.id == id,
                StrategyModel.deleted_at.is_(None),
            )
            .values(
                is_active=False,
                updated_at=datetime.now(UTC),
            )
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return (result.rowcount or 0) > 0
