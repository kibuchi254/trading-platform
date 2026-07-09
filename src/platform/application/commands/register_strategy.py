"""Register (create + activate) a strategy in one step.

Distinct from :mod:`platform.application.commands.create_strategy`, which
creates a Strategy row in the ``draft`` state (``is_active=False``).
This command is the "production register" path — the strategy is created
and immediately activated, ready for the strategy engine to subscribe to
bar-close events on its behalf.
"""

from __future__ import annotations

from datetime import UTC, datetime
from platform.core.exceptions import ConflictError
from platform.core.logging import get_logger
from platform.db.models import Strategy as StrategyModel
from platform.db.session import db_context
from platform.events.bus import get_event_bus
from platform.events.topics import Topic
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

_log = get_logger(__name__)


# ── Command + DTO ──────────────────────────────────────────────────────────


class RegisterStrategyCommand(BaseModel):
    org_id: UUID
    user_id: UUID
    name: str
    slug: str
    kind: str  # ema_cross | rsi_reversion | smc_ob | custom
    config: dict = {}
    description: str | None = None


class RegisterStrategyResult(BaseModel):
    id: UUID
    name: str
    slug: str
    kind: str
    is_active: bool
    registered_at: str


# ── Handler ─────────────────────────────────────────────────────────────────


async def handle_register_strategy(cmd: RegisterStrategyCommand) -> RegisterStrategyResult:
    """Create the Strategy row and flip ``is_active=True`` in one transaction.

    Raises :class:`ConflictError` if the (org_id, slug) pair is already taken.
    """
    async with db_context() as db:
        existing = (
            await db.execute(
                select(StrategyModel).where(
                    StrategyModel.org_id == cmd.org_id,
                    StrategyModel.slug == cmd.slug,
                    StrategyModel.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError(f"Strategy slug already exists: {cmd.slug}")

        strategy = StrategyModel(
            org_id=cmd.org_id,
            name=cmd.name,
            slug=cmd.slug,
            kind=cmd.kind,
            config=cmd.config,
            description=cmd.description,
            is_active=True,  # registered = active
        )
        db.add(strategy)
        try:
            await db.commit()
        except Exception as e:
            await db.rollback()
            raise ConflictError(f"Strategy slug already exists: {cmd.slug}") from e
        await db.refresh(strategy)

        result = RegisterStrategyResult(
            id=strategy.id,
            name=strategy.name,
            slug=strategy.slug,
            kind=strategy.kind,
            is_active=bool(strategy.is_active),
            registered_at=strategy.created_at.isoformat()
            if strategy.created_at
            else datetime.now(UTC).isoformat(),
        )

    await get_event_bus().publish(
        Topic.SIGNALS,
        {
            "type": "strategy_registered",
            "org_id": str(cmd.org_id),
            "strategy_id": str(result.id),
            "slug": result.slug,
            "kind": result.kind,
            "is_active": result.is_active,
            "actor_id": str(cmd.user_id),
        },
    )
    _log.info(
        "strategy_registered",
        strategy_id=str(result.id),
        slug=result.slug,
        kind=result.kind,
    )
    return result
