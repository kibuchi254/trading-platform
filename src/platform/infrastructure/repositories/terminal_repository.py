"""TerminalRepository — persistence for the Terminal ORM model.

The Terminal has no dedicated domain aggregate (its lifecycle is managed by
the bridge layer via `TerminalRegistered` / `TerminalWentOffline` events).
`to_domain` / `from_domain` are identity-style pass-throughs so the repository
keeps the same shape as the others and a future aggregate can be dropped in
without touching callers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from platform.db.models import Terminal


class TerminalRepository:
    """Async repository for Terminal rows."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Conversions ─────────────────────────────────────────────────────────

    @staticmethod
    def to_domain(m: Terminal) -> Terminal:
        return m

    @staticmethod
    def from_domain(e: Terminal) -> Terminal:
        return e

    # ── Reads ───────────────────────────────────────────────────────────────

    async def get(self, id: UUID) -> Terminal | None:
        return await self.db.get(Terminal, id)

    async def get_by_terminal_id(self, terminal_id: str) -> Terminal | None:
        """Lookup by the externally-known terminal_id (e.g. 'mt5-exness-01')."""
        stmt = select(Terminal).where(Terminal.terminal_id == terminal_id)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def list_by_org(
        self, org_id: UUID, *, status: str | None = None, limit: int = 200,
    ) -> list[Terminal]:
        stmt = select(Terminal).where(Terminal.org_id == org_id)
        if status:
            stmt = stmt.where(Terminal.status == status)
        stmt = stmt.order_by(Terminal.last_heartbeat_at.desc().nullslast()).limit(limit)
        return list((await self.db.execute(stmt)).scalars().all())

    async def list_by_status(self, org_id: UUID, status: str) -> list[Terminal]:
        stmt = select(Terminal).where(
            Terminal.org_id == org_id, Terminal.status == status,
        ).order_by(Terminal.last_heartbeat_at.desc().nullslast())
        return list((await self.db.execute(stmt)).scalars().all())

    # ── Writes ──────────────────────────────────────────────────────────────

    async def add(self, entity: Terminal) -> Terminal:
        self.db.add(entity)
        await self.db.flush()
        return entity

    async def save(self, entity: Terminal) -> Terminal:
        # Attached objects are auto-tracked by the session; flush writes them.
        if entity not in self.db:
            self.db.add(entity)
        await self.db.flush()
        return entity

    async def update_heartbeat(
        self, id: UUID, *, ip: str | None = None, status: str = "online",
    ) -> bool:
        values: dict = {
            "last_heartbeat_at": datetime.now(timezone.utc),
            "status": status,
            "updated_at": datetime.now(timezone.utc),
        }
        if ip is not None:
            values["last_seen_ip"] = ip
        stmt = update(Terminal).where(Terminal.id == id).values(**values)
        result = await self.db.execute(stmt)
        await self.db.flush()
        return (result.rowcount or 0) > 0

    async def update_status(self, id: UUID, status: str) -> bool:
        stmt = update(Terminal).where(Terminal.id == id).values(
            status=status,
            updated_at=datetime.now(timezone.utc),
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return (result.rowcount or 0) > 0
