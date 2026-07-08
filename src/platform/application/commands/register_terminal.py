"""Register a terminal — upsert the Terminal row when a terminal first connects."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

from platform.core.logging import get_logger
from platform.db.models import Terminal
from platform.db.session import db_context

_log = get_logger(__name__)


class RegisterTerminalCommand(BaseModel):
    org_id: UUID
    terminal_id: str  # external
    broker_id: UUID
    broker_account: str
    adapter_kind: str = "mt5"
    version: str | None = None
    symbols: list[str] = []
    capabilities: dict = {}


async def handle_register_terminal(cmd: RegisterTerminalCommand) -> dict[str, str]:
    async with db_context() as db:
        stmt = select(Terminal).where(
            Terminal.terminal_id == cmd.terminal_id, Terminal.org_id == cmd.org_id
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing is None:
            t = Terminal(
                org_id=cmd.org_id,
                broker_id=cmd.broker_id,
                terminal_id=cmd.terminal_id,
                broker_account=cmd.broker_account,
                adapter_kind=cmd.adapter_kind,
                version=cmd.version,
                status="online",
                last_heartbeat_at=datetime.now(timezone.utc),
                symbols=cmd.symbols,
                capabilities=cmd.capabilities,
            )
            db.add(t)
            _log.info("terminal_row_created", terminal_id=cmd.terminal_id, org_id=str(cmd.org_id))
        else:
            existing.status = "online"
            existing.last_heartbeat_at = datetime.now(timezone.utc)
            if cmd.version:
                existing.version = cmd.version
            if cmd.symbols:
                existing.symbols = cmd.symbols
            if cmd.capabilities:
                existing.capabilities = cmd.capabilities
        await db.commit()
    return {"terminal_id": cmd.terminal_id, "status": "registered"}
