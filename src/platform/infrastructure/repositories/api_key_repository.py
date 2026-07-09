"""APIKeyRepository — persistence for the APIKey aggregate.

API keys are hashed at rest; only the 8-char prefix is stored in plaintext for
UI display. Revocation is implemented as a hard delete (no `is_revoked` column
on the ORM) — once a row is gone the key cannot validate. `update_last_used`
is a write-light touch used on every authenticated request.
"""

from __future__ import annotations

from datetime import UTC, datetime
from platform.db.models import APIKey as APIKeyModel
from platform.domain.identity import APIKey, APIKeyPrefix, Scopes
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession


class APIKeyRepository:
    """Async repository for the APIKey aggregate."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Conversions ─────────────────────────────────────────────────────────

    @staticmethod
    def to_domain(m: APIKeyModel) -> APIKey:
        key = APIKey(
            id=m.id,
            org_id=m.org_id,
            user_id=m.user_id,
            name=m.name,
            key_prefix=APIKeyPrefix(value=m.key_prefix),
            key_hash=m.key_hash,
            scopes=Scopes.from_list(list(m.scopes or [])),
            expires_at=m.expires_at,
            last_used_at=m.last_used_at,
            created_at=m.created_at,
            is_revoked=False,
        )
        return key

    @staticmethod
    def from_domain(e: APIKey) -> APIKeyModel:
        return APIKeyModel(
            id=e.id,
            org_id=e.org_id,
            user_id=e.user_id,
            name=e.name,
            key_prefix=e.key_prefix.value,
            key_hash=e.key_hash,
            scopes=e.scopes.to_list(),
            expires_at=e.expires_at,
            last_used_at=e.last_used_at,
        )

    # ── Reads ───────────────────────────────────────────────────────────────

    async def get(self, id: UUID) -> APIKey | None:
        m = await self.db.get(APIKeyModel, id)
        return self.to_domain(m) if m else None

    async def get_by_prefix(self, prefix: str) -> APIKey | None:
        """Lookup by the 8-char UI prefix. Returns None if revoked (deleted)."""
        stmt = select(APIKeyModel).where(APIKeyModel.key_prefix == prefix)
        m = (await self.db.execute(stmt)).scalar_one_or_none()
        return self.to_domain(m) if m else None

    async def list_by_user(self, user_id: UUID) -> list[APIKey]:
        stmt = (
            select(APIKeyModel)
            .where(APIKeyModel.user_id == user_id)
            .order_by(APIKeyModel.created_at.desc())
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [self.to_domain(r) for r in rows]

    # ── Writes ──────────────────────────────────────────────────────────────

    async def add(self, entity: APIKey) -> APIKey:
        self.db.add(self.from_domain(entity))
        await self.db.flush()
        return entity

    async def revoke(self, id: UUID) -> bool:
        """Hard-delete the row. Idempotent: returns True if a row was deleted."""
        stmt = delete(APIKeyModel).where(APIKeyModel.id == id)
        result = await self.db.execute(stmt)
        await self.db.flush()
        return (result.rowcount or 0) > 0

    async def update_last_used(self, id: UUID) -> bool:
        """Bump last_used_at to now. Cheap write used on every auth."""
        stmt = (
            update(APIKeyModel)
            .where(APIKeyModel.id == id)
            .values(
                last_used_at=datetime.now(UTC),
            )
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return (result.rowcount or 0) > 0
