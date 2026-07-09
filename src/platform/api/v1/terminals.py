"""Terminals REST router — register / list / detail / heartbeat status."""

from __future__ import annotations

from platform.core.dependencies import CurrentUser, get_current_user
from platform.db.models import Terminal
from platform.db.session import get_db
from platform.infrastructure.mt5_bridge.registry import get_registry
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/terminals", tags=["terminals"])


class TerminalOut(BaseModel):
    id: UUID
    terminal_id: str
    broker: str | None
    broker_account: str
    adapter_kind: str
    version: str | None
    status: str
    last_heartbeat_at: str | None
    symbols: list[str]
    capabilities: dict
    is_online: bool

    model_config = {"from_attributes": True}


@router.get("", response_model=list[TerminalOut])
async def list_terminals(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[TerminalOut]:
    stmt = select(Terminal).where(Terminal.org_id == user.org_id)
    if status_filter:
        stmt = stmt.where(Terminal.status == status_filter)
    rows = (await db.execute(stmt)).scalars().all()
    registry = get_registry()
    out: list[TerminalOut] = []
    for r in rows:
        live = await registry.get(r.terminal_id)
        out.append(
            TerminalOut(
                id=r.id,
                terminal_id=r.terminal_id,
                broker=None,
                broker_account=r.broker_account,
                adapter_kind=r.adapter_kind,
                version=r.version,
                status=r.status,
                last_heartbeat_at=r.last_heartbeat_at.isoformat() if r.last_heartbeat_at else None,
                symbols=r.symbols,
                capabilities=r.capabilities,
                is_online=live is not None and live.status == "online",
            )
        )
    return out


@router.get("/{terminal_id}", response_model=TerminalOut)
async def get_terminal(
    terminal_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TerminalOut:
    stmt = select(Terminal).where(
        Terminal.terminal_id == terminal_id, Terminal.org_id == user.org_id
    )
    r = (await db.execute(stmt)).scalar_one_or_none()
    if r is None:
        from platform.core.exceptions import NotFoundError

        raise NotFoundError(f"Terminal {terminal_id} not found")
    registry = get_registry()
    live = await registry.get(terminal_id)
    return TerminalOut(
        id=r.id,
        terminal_id=r.terminal_id,
        broker=None,
        broker_account=r.broker_account,
        adapter_kind=r.adapter_kind,
        version=r.version,
        status=r.status,
        last_heartbeat_at=r.last_heartbeat_at.isoformat() if r.last_heartbeat_at else None,
        symbols=r.symbols,
        capabilities=r.capabilities,
        is_online=live is not None and live.status == "online",
    )


@router.post("/{terminal_id}/sync-positions")
async def sync_positions(
    terminal_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, str]:
    from platform.infrastructure.mt5_bridge.client import get_bridge_client

    reply = await get_bridge_client().sync_positions(terminal_id=terminal_id)
    return {"status": "ok", "received": str(len(reply.payload.get("positions", [])))}


@router.post("/{terminal_id}/sync-account")
async def sync_account(
    terminal_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, object]:
    from platform.infrastructure.mt5_bridge.client import get_bridge_client

    reply = await get_bridge_client().sync_account(terminal_id=terminal_id)
    return {"status": "ok", "account": reply.payload}
