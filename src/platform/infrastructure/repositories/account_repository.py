"""AccountRepository — persistence for the trading Account ORM model.

An Account is the balance against which Positions are booked on a Terminal.
The repository handles balance / equity / margin updates coming back from
the bridge's periodic account-sync messages.

There is no dedicated domain aggregate for Account — its lifecycle is purely
operational (created when a Terminal registers, mutated only by bridge sync).
The to_domain / from_domain helpers are therefore identity pass-throughs,
kept for shape-consistency with sibling repositories so that a future
Account aggregate can be slotted in without touching callers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from platform.db.models import Account


class AccountRepository:
    """Async repository for the Account ORM model."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Conversions ─────────────────────────────────────────────────────────
    # No dedicated domain aggregate for Account — to_domain / from_domain are
    # identity pass-throughs kept for shape-consistency with sibling repos.
    # A future `Account` aggregate can be substituted here without touching
    # the application layer.

    @staticmethod
    def to_domain(m: Account) -> Account:
        return m

    @staticmethod
    def from_domain(e: Account) -> Account:
        return e

    # ── Reads ───────────────────────────────────────────────────────────────

    async def get(self, id: UUID) -> Account | None:
        return await self.db.get(Account, id)

    async def get_by_terminal(self, terminal_id: UUID) -> Account | None:
        stmt = select(Account).where(Account.terminal_id == terminal_id)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def list_by_org(self, org_id: UUID) -> list[Account]:
        stmt = select(Account).where(Account.org_id == org_id).order_by(
            Account.created_at.desc(),
        )
        return list((await self.db.execute(stmt)).scalars().all())

    # ── Writes ──────────────────────────────────────────────────────────────

    async def add(self, entity: Account) -> Account:
        self.db.add(entity)
        await self.db.flush()
        return entity

    async def save(self, entity: Account) -> Account:
        if entity not in self.db:
            self.db.add(entity)
        await self.db.flush()
        return entity

    async def update_balance(
        self, id: UUID, *, equity: float, balance: float,
        margin: float, free_margin: float,
    ) -> bool:
        """Atomically refresh the account snapshot from a bridge sync message."""
        stmt = update(Account).where(Account.id == id).values(
            equity=equity,
            balance=balance,
            margin=margin,
            free_margin=free_margin,
            last_synced_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return (result.rowcount or 0) > 0
