"""Create a new strategy."""
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from platform.core.exceptions import ConflictError
from platform.db.models import Strategy as StrategyModel
from platform.db.session import db_context


class CreateStrategyCommand(BaseModel):
    org_id: UUID
    user_id: UUID
    name: str
    slug: str
    kind: str
    config: dict = {}
    description: str | None = None
    symbols: list[str] = []
    timeframes: list[str] = ["M15"]


class CreateStrategyResult(BaseModel):
    id: UUID
    name: str
    slug: str
    kind: str
    is_active: bool


async def handle_create_strategy(cmd: CreateStrategyCommand) -> CreateStrategyResult:
    async with db_context() as db:
        s = StrategyModel(
            org_id=cmd.org_id,
            name=cmd.name,
            slug=cmd.slug,
            kind=cmd.kind,
            config=cmd.config,
            description=cmd.description,
            is_active=False,  # created as draft
        )
        db.add(s)
        try:
            await db.commit()
        except Exception as e:
            await db.rollback()
            raise ConflictError(f"Strategy slug already exists: {cmd.slug}") from e
        await db.refresh(s)
        return CreateStrategyResult(
            id=s.id, name=s.name, slug=s.slug, kind=s.kind, is_active=s.is_active,
        )
