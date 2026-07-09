"""RiskEventRepository — persistence for the RiskEvent aggregate.

Converts between the SQLAlchemy `RiskEvent` row and the domain `RiskEvent`
aggregate. RiskEvents are append-mostly: created on breach, escalated upward
in severity, then resolved with operator notes. `resolve` is exposed as a
convenience shortcut for the resolution endpoint.
"""

from __future__ import annotations

from datetime import UTC, datetime
from platform.db.models import RiskEvent as RiskEventModel
from platform.domain.risk import (
    RiskAction,
    RiskEvent,
    RiskRuleName,
    RiskSeverity,
)
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class RiskEventRepository:
    """Async repository for the RiskEvent aggregate."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Conversions ─────────────────────────────────────────────────────────

    @staticmethod
    def to_domain(m: RiskEventModel) -> RiskEvent:
        event = RiskEvent(
            id=m.id,
            org_id=m.org_id,
            terminal_id=m.terminal_id,
            rule=RiskRuleName(m.rule),
            severity=RiskSeverity(m.severity),
            action=RiskAction(m.action),
            details=m.details or {},
            order_id=m.order_id,
            created_at=m.created_at,
        )
        # Resolution state lives on the aggregate but has no dedicated ORM
        # column — we tunnel it through `details`. On read, hydrate the
        # in-memory fields so the aggregate reflects what's persisted.
        resolution = (m.details or {}).get("resolution")
        resolved_at = (m.details or {}).get("resolved_at")
        if resolution and resolved_at:
            event.resolved_at = datetime.fromisoformat(resolved_at)  # type: ignore[assignment]
            event.resolution = resolution  # type: ignore[assignment]
        # Drain the spurious RiskLimitBreached event emitted by __post_init__.
        event.collect_events()
        return event

    @staticmethod
    def from_domain(e: RiskEvent) -> RiskEventModel:
        details = dict(e.details)
        if e.resolved_at is not None and e.resolution:
            details["resolution"] = e.resolution
            details["resolved_at"] = e.resolved_at.isoformat()
        return RiskEventModel(
            id=e.id,
            org_id=e.org_id,
            terminal_id=e.terminal_id,
            rule=e.rule.value,
            severity=e.severity.value,
            action=e.action.value,
            details=details,
            order_id=e.order_id,
        )

    # ── Reads ───────────────────────────────────────────────────────────────

    async def get(self, id: UUID) -> RiskEvent | None:
        m = await self.db.get(RiskEventModel, id)
        return self.to_domain(m) if m else None

    async def list_by_org(
        self,
        org_id: UUID,
        *,
        unresolved_only: bool = False,
        limit: int = 200,
    ) -> list[RiskEvent]:
        stmt = select(RiskEventModel).where(RiskEventModel.org_id == org_id)
        if unresolved_only:
            stmt = stmt.where(RiskEventModel.details["resolved_at"].is_(None))
        stmt = stmt.order_by(RiskEventModel.created_at.desc()).limit(limit)
        rows = (await self.db.execute(stmt)).scalars().all()
        return [self.to_domain(r) for r in rows]

    async def list_by_rule(
        self,
        org_id: UUID,
        rule: str,
        *,
        limit: int = 100,
    ) -> list[RiskEvent]:
        stmt = (
            select(RiskEventModel)
            .where(RiskEventModel.org_id == org_id, RiskEventModel.rule == rule)
            .order_by(RiskEventModel.created_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [self.to_domain(r) for r in rows]

    async def list_unresolved(self, org_id: UUID) -> list[RiskEvent]:
        return await self.list_by_org(org_id, unresolved_only=True, limit=500)

    # ── Writes ──────────────────────────────────────────────────────────────

    async def add(self, entity: RiskEvent) -> RiskEvent:
        self.db.add(self.from_domain(entity))
        await self.db.flush()
        return entity

    async def resolve(self, id: UUID, notes: str) -> bool:
        """Stamp resolution notes + timestamp into the JSONB details blob."""
        if not notes.strip():
            from platform.core.exceptions import DomainError

            raise DomainError("resolution notes required")
        m = await self.db.get(RiskEventModel, id)
        if m is None:
            return False
        details = dict(m.details or {})
        if details.get("resolved_at"):
            return False  # already resolved
        details["resolution"] = notes.strip()
        details["resolved_at"] = datetime.now(UTC).isoformat()
        m.details = details
        await self.db.flush()
        return True
