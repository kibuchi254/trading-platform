"""Strategies REST router — CRUD + activate/deactivate."""

from __future__ import annotations

from platform.core.dependencies import CurrentUser, get_current_user
from platform.db.models import Strategy
from platform.db.session import get_db
from platform.strategies.sdk import get_strategy_registry
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/strategies", tags=["strategies"])


class StrategyCreate(BaseModel):
    name: str
    slug: str
    kind: str
    config: dict = {}
    description: str | None = None


class StrategyOut(BaseModel):
    id: UUID
    name: str
    slug: str
    kind: str
    version: str
    config: dict
    is_active: bool
    description: str | None

    model_config = {"from_attributes": True}


@router.get("/available")
async def list_available_strategies() -> list[dict[str, object]]:
    """List strategies the SDK knows about (built-in + registered plugins)."""
    reg = get_strategy_registry()
    return [
        {"name": cls.name, "version": cls.version, "default_config": cls.default_config}
        for cls in reg._strategies.values()
    ]


@router.post("", response_model=StrategyOut, status_code=201)
async def create_strategy(
    req: StrategyCreate,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StrategyOut:
    s = Strategy(
        org_id=user.org_id,
        name=req.name,
        slug=req.slug,
        kind=req.kind,
        config=req.config,
        description=req.description,
    )
    db.add(s)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e
    await db.refresh(s)
    return StrategyOut.model_validate(s)


@router.get("", response_model=list[StrategyOut])
async def list_strategies(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[StrategyOut]:
    stmt = select(Strategy).where(Strategy.org_id == user.org_id, Strategy.deleted_at.is_(None))
    rows = (await db.execute(stmt)).scalars().all()
    return [StrategyOut.model_validate(r) for r in rows]


@router.post("/{strategy_id}/activate", response_model=StrategyOut)
async def activate_strategy(
    strategy_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StrategyOut:
    s = await db.get(Strategy, strategy_id)
    if s is None or s.org_id != user.org_id:
        raise HTTPException(status_code=404, detail="Strategy not found")
    s.is_active = True
    await db.commit()
    await db.refresh(s)
    return StrategyOut.model_validate(s)


@router.post("/{strategy_id}/deactivate", response_model=StrategyOut)
async def deactivate_strategy(
    strategy_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StrategyOut:
    s = await db.get(Strategy, strategy_id)
    if s is None or s.org_id != user.org_id:
        raise HTTPException(status_code=404, detail="Strategy not found")
    s.is_active = False
    await db.commit()
    await db.refresh(s)
    return StrategyOut.model_validate(s)
