"""Brokers REST router — broker management.

The brokers table holds broker connection metadata per org. Org-scoped.
"""

from __future__ import annotations

from datetime import UTC, datetime
from platform.core.dependencies import CurrentUser, get_current_user
from platform.core.exceptions import NotFoundError
from platform.db.models import Broker
from platform.db.session import get_db
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/brokers", tags=["brokers"])


class BrokerCreate(BaseModel):
    name: str
    code: str  # exness | icmarkets | pepperstone
    adapter_kind: str = "mt5"  # mt5 | fix | crypto | paper
    credentials: dict = {}


class BrokerOut(BaseModel):
    id: UUID
    name: str
    code: str
    adapter_kind: str
    is_active: bool
    created_at: str

    model_config = {"from_attributes": True}


def _to_out(b: Broker) -> BrokerOut:
    return BrokerOut(
        id=b.id,
        name=b.name,
        code=b.code,
        adapter_kind=b.adapter_kind,
        is_active=b.is_active,
        created_at=b.created_at.isoformat() if b.created_at else None,
    )


@router.get("", response_model=list[BrokerOut])
async def list_brokers(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BrokerOut]:
    stmt = select(Broker).where(Broker.org_id == user.org_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [_to_out(r) for r in rows]


@router.post("", response_model=BrokerOut, status_code=201)
async def create_broker(
    req: BrokerCreate,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BrokerOut:
    b = Broker(
        org_id=user.org_id,
        name=req.name,
        code=req.code,
        adapter_kind=req.adapter_kind,
        credentials=req.credentials,
    )
    db.add(b)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e
    await db.refresh(b)
    return _to_out(b)


@router.patch("/{broker_id}/deactivate", response_model=BrokerOut)
async def deactivate_broker(
    broker_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BrokerOut:
    b = await db.get(Broker, broker_id)
    if b is None or b.org_id != user.org_id:
        raise NotFoundError(f"Broker {broker_id} not found")
    b.is_active = False
    b.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(b)
    return _to_out(b)
