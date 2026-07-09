"""AuditRepository — append-only persistence for AuditLog rows.

The audit log is write-heavy and never updated. The repository therefore
exposes only `add` (from a dict-shaped entry, to keep the call site terse) and
a small set of read filters used by the audit-trail UI.
"""

from __future__ import annotations

from platform.db.models import AuditLog
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class AuditRepository:
    """Async repository for the AuditLog ORM model."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Conversions ─────────────────────────────────────────────────────────
    # No domain aggregate for audit entries — to_domain / from_domain are
    # identity pass-throughs kept for shape-consistency.

    @staticmethod
    def to_domain(m: AuditLog) -> AuditLog:
        return m

    @staticmethod
    def from_domain(e: AuditLog) -> AuditLog:
        return e

    # ── Writes ──────────────────────────────────────────────────────────────

    async def add(self, entry: dict[str, Any]) -> AuditLog:
        """Insert an audit row from a dict. Required keys: action. Optional:
        org_id, actor_id, actor_type, resource_type, resource_id, ip,
        user_agent, payload. `ts` defaults to now() at the DB layer."""
        m = AuditLog(
            org_id=entry.get("org_id"),
            actor_id=entry.get("actor_id"),
            actor_type=entry.get("actor_type", "user"),
            action=entry["action"],
            resource_type=entry.get("resource_type"),
            resource_id=entry.get("resource_id"),
            ip=entry.get("ip"),
            user_agent=entry.get("user_agent"),
            payload=entry.get("payload") or {},
        )
        self.db.add(m)
        await self.db.flush()
        return m

    # ── Reads ───────────────────────────────────────────────────────────────

    async def list_by_actor(
        self,
        actor_id: UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(AuditLog.actor_id == actor_id)
            .order_by(AuditLog.ts.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def list_by_org(
        self,
        org_id: UUID,
        *,
        action: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLog]:
        stmt = select(AuditLog).where(AuditLog.org_id == org_id)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        stmt = stmt.order_by(AuditLog.ts.desc()).limit(limit).offset(offset)
        return list((await self.db.execute(stmt)).scalars().all())

    async def list_by_action(
        self,
        action: str,
        *,
        org_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLog]:
        stmt = select(AuditLog).where(AuditLog.action == action)
        if org_id is not None:
            stmt = stmt.where(AuditLog.org_id == org_id)
        stmt = stmt.order_by(AuditLog.ts.desc()).limit(limit).offset(offset)
        return list((await self.db.execute(stmt)).scalars().all())

    async def get(self, id: int) -> AuditLog | None:
        """Lookup by integer primary key (audit rows use a serial id)."""
        return await self.db.get(AuditLog, id)
