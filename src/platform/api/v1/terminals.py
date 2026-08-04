"""Terminals REST router — register / list / detail / heartbeat status."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform.core.config import get_settings
from platform.core.dependencies import CurrentUser, get_current_user
from platform.db.models import Terminal
from platform.db.session import get_db
from platform.infrastructure.mt5_bridge.registry import get_registry

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


def _is_recently_alive(heartbeat: datetime | None, timeout_seconds: int) -> bool:
    """Return True if the heartbeat is within the timeout window."""
    if heartbeat is None:
        return False
    # Ensure both are offset-aware for comparison
    now = datetime.now(UTC)
    if heartbeat.tzinfo is None:
        # Treat naive as UTC
        heartbeat = heartbeat.replace(tzinfo=UTC)
    return (now - heartbeat) < timedelta(seconds=timeout_seconds)


@router.get("", response_model=list[TerminalOut])
async def list_terminals(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[TerminalOut]:
    settings = get_settings()
    hb_timeout = settings.bridge_heartbeat_timeout_seconds

    stmt = select(Terminal).where(Terminal.org_id == user.org_id)
    if status_filter:
        stmt = stmt.where(Terminal.status == status_filter)
    rows = (await db.execute(stmt)).scalars().all()
    registry = get_registry()
    out: list[TerminalOut] = []
    db_terminal_ids = set()

    for r in rows:
        db_terminal_ids.add(r.terminal_id)
        live = await registry.get(r.terminal_id)
        # Online if in-memory registry says so OR DB heartbeat is recent
        is_online = (live is not None and live.status == "online") or _is_recently_alive(
            r.last_heartbeat_at, hb_timeout
        )
        out.append(
            TerminalOut(
                id=r.id,
                terminal_id=r.terminal_id,
                broker=r.broker_account if not live else live.broker,
                broker_account=r.broker_account,
                adapter_kind=r.adapter_kind,
                version=r.version if not live else live.version,
                status="online" if is_online else r.status,
                last_heartbeat_at=live.last_heartbeat_at.isoformat()
                if live and live.last_heartbeat_at
                else (r.last_heartbeat_at.isoformat() if r.last_heartbeat_at else None),
                symbols=r.symbols if not live else live.symbols,
                capabilities=r.capabilities if not live else live.capabilities,
                is_online=is_online,
            )
        )

    # Merge live terminals from registry that are connected over WebSockets/HTTPS
    live_records = await registry.list_online()
    for live in live_records:
        if live.terminal_id not in db_terminal_ids:
            out.append(
                TerminalOut(
                    id=uuid4(),
                    terminal_id=live.terminal_id,
                    broker=live.broker,
                    broker_account=live.account,
                    adapter_kind="mt5",
                    version=live.version,
                    status="online",
                    last_heartbeat_at=live.last_heartbeat_at.isoformat()
                    if live.last_heartbeat_at
                    else None,
                    symbols=live.symbols,
                    capabilities=live.capabilities,
                    is_online=True,
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
    """Return the latest cached account state for the terminal.

    For HTTP-polling terminals the EA pushes balance/equity/margin every few
    seconds via /bridge-http/poll, so we return the cached snapshot directly —
    sending a cmd.account.sync would 500 (HttpSession has no send()) and is
    redundant. For WebSocket terminals we fall back to the bridge command if
    no snapshot is cached yet.
    """
    registry = get_registry()
    snapshot = await registry.get_account(terminal_id)
    if snapshot is not None:
        return {"status": "ok", "account": snapshot}

    # No cached snapshot (e.g. WS terminal that hasn't pushed an update) —
    # ask the terminal to sync. Requires a real WS BridgeSession.send.
    from platform.infrastructure.mt5_bridge.client import get_bridge_client

    reply = await get_bridge_client().sync_account(terminal_id=terminal_id)
    return {"status": "ok", "account": reply.payload}


@router.post("/{terminal_id}/flatten")
async def flatten_terminal(
    terminal_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Emergency button — close all positions + cancel all orders on a terminal."""
    from platform.application.commands.flatten_all import FlattenAllCommand, handle_flatten_all

    result = await handle_flatten_all(
        FlattenAllCommand(
            org_id=user.org_id,
            user_id=user.user_id,
            terminal_id=terminal_id,
            reason=f"manual by {user.user_id}",
        )
    )
    return result.model_dump(mode="json")
