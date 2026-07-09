"""UserRepository — persistence for the User aggregate.

Converts between the SQLAlchemy `UserModel` row and the domain `User`
aggregate. `password_hash` is opaque to the repository — hashing / verification
live in `platform.core.security`. Soft-delete is honoured: rows with
`deleted_at` set are invisible to all reads.
"""

from __future__ import annotations

from datetime import UTC, datetime
from platform.db.models import User as UserModel
from platform.domain.identity import Email, User, UserRole
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


class UserRepository:
    """Async repository for the User aggregate."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Conversions ─────────────────────────────────────────────────────────

    @staticmethod
    def to_domain(m: UserModel) -> User:
        user = User(
            id=m.id,
            org_id=m.org_id,
            email=Email(address=m.email),
            display_name=m.display_name,
            role=UserRole(m.role),
            is_active=bool(m.is_active),
            last_login_at=m.last_login_at,
            created_at=m.created_at,
        )
        # Side-channel ORM-only field for round-trip via save().
        user.password_hash = m.password_hash  # type: ignore[attr-defined]
        return user

    @staticmethod
    def from_domain(e: User) -> UserModel:
        return UserModel(
            id=e.id,
            org_id=e.org_id,
            email=e.email.address,
            password_hash=getattr(e, "password_hash", ""),
            display_name=e.display_name,
            role=e.role.value,
            is_active=e.is_active,
            last_login_at=e.last_login_at,
        )

    # ── Reads ───────────────────────────────────────────────────────────────

    async def get(self, id: UUID) -> User | None:
        m = await self.db.get(UserModel, id)
        if m is None or m.deleted_at is not None:
            return None
        return self.to_domain(m)

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(UserModel).where(
            UserModel.email == email.lower(),
            UserModel.deleted_at.is_(None),
        )
        m = (await self.db.execute(stmt)).scalar_one_or_none()
        return self.to_domain(m) if m else None

    async def list_by_org(self, org_id: UUID) -> list[User]:
        stmt = (
            select(UserModel)
            .where(
                UserModel.org_id == org_id,
                UserModel.deleted_at.is_(None),
            )
            .order_by(UserModel.created_at.desc())
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [self.to_domain(r) for r in rows]

    # ── Writes ──────────────────────────────────────────────────────────────

    async def add(self, entity: User) -> User:
        self.db.add(self.from_domain(entity))
        await self.db.flush()
        return entity

    async def save(self, entity: User) -> User:
        m = await self.db.get(UserModel, entity.id)
        if m is None:
            return await self.add(entity)
        m.email = entity.email.address
        m.password_hash = getattr(entity, "password_hash", m.password_hash)
        m.display_name = entity.display_name
        m.role = entity.role.value
        m.is_active = entity.is_active
        m.last_login_at = entity.last_login_at
        await self.db.flush()
        return entity

    async def update_last_login(self, id: UUID) -> bool:
        stmt = (
            update(UserModel)
            .where(
                UserModel.id == id,
                UserModel.deleted_at.is_(None),
            )
            .values(
                last_login_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return (result.rowcount or 0) > 0

    async def deactivate(self, id: UUID) -> bool:
        """Soft-delete: set is_active=False and deleted_at=now. Idempotent."""
        now = datetime.now(UTC)
        stmt = (
            update(UserModel)
            .where(
                UserModel.id == id,
                UserModel.deleted_at.is_(None),
            )
            .values(is_active=False, deleted_at=now, updated_at=now)
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return (result.rowcount or 0) > 0
