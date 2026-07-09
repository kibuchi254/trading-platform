"""List strategies for an org, optionally filtered to active only.

Vertical slice:

  API → query → DB: select Strategy rows by org_id (active_only filter)
        → return DTOs
"""

from __future__ import annotations

from datetime import datetime
from platform.db.models import Strategy as StrategyModel
from platform.db.session import db_context
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

# ── Query + DTO ────────────────────────────────────────────────────────────


class ListStrategiesQuery(BaseModel):
    org_id: UUID
    active_only: bool = False


class StrategySummary(BaseModel):
    id: UUID
    name: str
    slug: str
    kind: str
    version: str
    is_active: bool
    description: str | None
    created_at: datetime


class ListStrategiesResult(BaseModel):
    strategies: list[StrategySummary]
    total: int


# ── Handler ─────────────────────────────────────────────────────────────────


async def handle_list_strategies(query: ListStrategiesQuery) -> ListStrategiesResult:
    """List strategies for the org (soft-deleted rows excluded)."""
    async with db_context() as db:
        stmt = select(StrategyModel).where(
            StrategyModel.org_id == query.org_id,
            StrategyModel.deleted_at.is_(None),
        )
        if query.active_only:
            stmt = stmt.where(StrategyModel.is_active.is_(True))
        stmt = stmt.order_by(StrategyModel.created_at.desc())
        rows = (await db.execute(stmt)).scalars().all()

    strategies = [
        StrategySummary(
            id=r.id,
            name=r.name,
            slug=r.slug,
            kind=r.kind,
            version=r.version or "1.0.0",
            is_active=bool(r.is_active),
            description=r.description,
            created_at=r.created_at,
        )
        for r in rows
    ]
    return ListStrategiesResult(strategies=strategies, total=len(strategies))
