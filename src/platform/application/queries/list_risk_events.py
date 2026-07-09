"""List risk events for an org with optional filters.

Vertical slice:

  API → query → DB: select RiskEvent rows by org_id (+ severity / rule / resolved filters)
        → return DTOs

Risk events are append-mostly records produced when a risk rule fires (see
:class:`RiskEngine` and :mod:`platform.application.commands.engage_kill_switch`).
The "resolved" filter is layered on top via the JSONB ``details`` blob —
events are considered resolved when ``details.resolved_at`` is present.
"""

from __future__ import annotations

from datetime import datetime
from platform.db.models import RiskEvent
from platform.db.session import db_context
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

# ── Query + DTO ────────────────────────────────────────────────────────────


class ListRiskEventsQuery(BaseModel):
    org_id: UUID
    severity: str | None = None  # info | warning | critical | kill
    rule: str | None = None  # kill_switch | max_daily_loss | ...
    resolved: bool = False  # False = unresolved only (default); True = all
    limit: int = 50


class RiskEventSummary(BaseModel):
    id: UUID
    terminal_id: UUID | None
    rule: str
    severity: str
    action: str
    details: dict
    order_id: UUID | None
    resolved: bool
    resolved_at: datetime | None
    created_at: datetime


class ListRiskEventsResult(BaseModel):
    events: list[RiskEventSummary]
    total: int


# ── Handler ─────────────────────────────────────────────────────────────────


async def handle_list_risk_events(query: ListRiskEventsQuery) -> ListRiskEventsResult:
    """Filter and paginate risk events for the org."""
    limit = max(1, min(query.limit, 500))

    async with db_context() as db:
        stmt = select(RiskEvent).where(RiskEvent.org_id == query.org_id)
        if query.severity is not None:
            stmt = stmt.where(RiskEvent.severity == query.severity)
        if query.rule is not None:
            stmt = stmt.where(RiskEvent.rule == query.rule)
        if not query.resolved:
            # Unresolved only — events whose details JSONB has no resolved_at key.
            stmt = stmt.where(RiskEvent.details["resolved_at"].is_(None))
        stmt = stmt.order_by(RiskEvent.created_at.desc()).limit(limit)
        rows = (await db.execute(stmt)).scalars().all()

    events = [
        RiskEventSummary(
            id=r.id,
            terminal_id=r.terminal_id,
            rule=r.rule,
            severity=r.severity,
            action=r.action,
            details=dict(r.details or {}),
            order_id=r.order_id,
            resolved=bool((r.details or {}).get("resolved_at")),
            resolved_at=_parse_dt((r.details or {}).get("resolved_at")),
            created_at=r.created_at,
        )
        for r in rows
    ]
    return ListRiskEventsResult(events=events, total=len(events))


def _parse_dt(raw) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
