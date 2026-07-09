"""Force terminal account sync — pull balance/equity/margin from MT5."""

from __future__ import annotations

from datetime import UTC, datetime
from platform.core.exceptions import NotFoundError
from platform.db.models import Account, Terminal
from platform.db.session import db_context
from platform.infrastructure.mt5_bridge.client import get_bridge_client
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select


class SyncAccountCommand(BaseModel):
    org_id: UUID
    user_id: UUID
    terminal_id: str


class SyncAccountResult(BaseModel):
    terminal_id: str
    balance: float
    equity: float
    margin: float
    free_margin: float
    currency: str
    leverage: int


async def handle_sync_account(cmd: SyncAccountCommand) -> SyncAccountResult:
    bridge = get_bridge_client()
    reply = await bridge.sync_account(terminal_id=cmd.terminal_id, timeout=10.0)
    payload = reply.payload

    async with db_context() as db:
        stmt = select(Terminal).where(
            Terminal.terminal_id == cmd.terminal_id, Terminal.org_id == cmd.org_id
        )
        terminal = (await db.execute(stmt)).scalar_one_or_none()
        if terminal is None:
            raise NotFoundError(f"Terminal {cmd.terminal_id} not found")

        # Find or create account row
        acct_stmt = select(Account).where(Account.terminal_id == terminal.id)
        acct = (await db.execute(acct_stmt)).scalar_one_or_none()
        if acct is None:
            acct = Account(
                org_id=cmd.org_id,
                terminal_id=terminal.id,
                broker_login=terminal.broker_account,
                currency=payload.get("currency", "USD"),
                leverage=int(payload.get("leverage", 100)),
            )
            db.add(acct)
        acct.balance = float(payload["balance"])
        acct.equity = float(payload["equity"])
        acct.margin = float(payload["margin"])
        acct.free_margin = float(payload["free_margin"])
        acct.currency = payload.get("currency", acct.currency)
        acct.leverage = int(payload.get("leverage", acct.leverage))
        acct.last_synced_at = datetime.now(UTC)
        await db.commit()

    return SyncAccountResult(
        terminal_id=cmd.terminal_id,
        balance=float(payload["balance"]),
        equity=float(payload["equity"]),
        margin=float(payload["margin"]),
        free_margin=float(payload["free_margin"]),
        currency=payload.get("currency", "USD"),
        leverage=int(payload.get("leverage", 100)),
    )
