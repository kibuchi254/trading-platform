"""Get a single terminal's detail — joins Terminal + Account + live counts.

Vertical slice:

  API → query → DB: load Terminal by external terminal_id + org_id
        → DB: load Account (if any) for the terminal
        → DB: count open Positions + pending Orders
        → bridge registry: live status
        → return composite DTO
"""

from __future__ import annotations

from platform.core.exceptions import NotFoundError
from platform.core.logging import get_logger
from platform.db.models import Account, Order, Position, Terminal
from platform.db.session import db_context
from platform.infrastructure.mt5_bridge.registry import get_registry
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select

_log = get_logger(__name__)

_PENDING_ORDER_STATUSES = ("pending", "submitted", "partial")


# ── Query + DTO ────────────────────────────────────────────────────────────


class GetTerminalDetailQuery(BaseModel):
    terminal_id: str  # external
    org_id: UUID


class AccountDetail(BaseModel):
    balance: float
    equity: float
    margin: float
    free_margin: float
    currency: str
    leverage: int
    last_synced_at: str | None


class TerminalDetail(BaseModel):
    id: UUID
    terminal_id: str
    broker_account: str
    adapter_kind: str
    version: str | None
    status: str  # live status
    last_heartbeat_at: str | None
    symbols: list[str]
    capabilities: dict
    open_positions_count: int
    pending_orders_count: int
    account: AccountDetail | None = None


# ── Handler ─────────────────────────────────────────────────────────────────


async def handle_get_terminal_detail(query: GetTerminalDetailQuery) -> TerminalDetail:
    """Compose the terminal detail view from Terminal + Account + counts."""
    async with db_context() as db:
        terminal = (
            await db.execute(
                select(Terminal).where(
                    Terminal.terminal_id == query.terminal_id,
                    Terminal.org_id == query.org_id,
                )
            )
        ).scalar_one_or_none()
        if terminal is None:
            raise NotFoundError(f"Terminal {query.terminal_id} not found")

        account = (
            await db.execute(select(Account).where(Account.terminal_id == terminal.id))
        ).scalar_one_or_none()

        open_positions_count = (
            await db.execute(
                select(func.count())
                .select_from(Position)
                .where(
                    Position.terminal_id == terminal.id,
                    Position.status == "open",
                )
            )
        ).scalar_one()

        pending_orders_count = (
            await db.execute(
                select(func.count())
                .select_from(Order)
                .where(
                    Order.terminal_id == terminal.id,
                    Order.status.in_(_PENDING_ORDER_STATUSES),
                )
            )
        ).scalar_one()

    # Live status from registry
    live_status = "offline"
    last_heartbeat = terminal.last_heartbeat_at
    try:
        live = await get_registry().get(query.terminal_id)
        if live is not None:
            live_status = live.status
            last_heartbeat = live.last_heartbeat_at
        elif terminal.status == "online":
            live_status = "offline"  # DB lies; registry is truth
        else:
            live_status = terminal.status
    except Exception:
        live_status = terminal.status

    return TerminalDetail(
        id=terminal.id,
        terminal_id=terminal.terminal_id,
        broker_account=terminal.broker_account,
        adapter_kind=terminal.adapter_kind,
        version=terminal.version,
        status=live_status,
        last_heartbeat_at=(last_heartbeat.isoformat() if last_heartbeat is not None else None),
        symbols=list(terminal.symbols or []),
        capabilities=dict(terminal.capabilities or {}),
        open_positions_count=int(open_positions_count or 0),
        pending_orders_count=int(pending_orders_count or 0),
        account=(
            AccountDetail(
                balance=float(account.balance or 0),
                equity=float(account.equity or 0),
                margin=float(account.margin or 0),
                free_margin=float(account.free_margin or 0),
                currency=account.currency,
                leverage=account.leverage,
                last_synced_at=(
                    account.last_synced_at.isoformat()
                    if account.last_synced_at is not None
                    else None
                ),
            )
            if account is not None
            else None
        ),
    )
