"""Native HTTP Bridge router for MT5 WebRequest (Zero-DLL connection)."""

from __future__ import annotations

from platform.infrastructure.mt5_bridge.registry import get_registry
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/bridge-http", tags=["bridge-http"])


class RegisterPayload(BaseModel):
    terminal_id: str
    broker: str | None = "Exness"
    account: int | str = 0
    version: str | None = "1.00"
    symbols: list[str] = []
    auth_token: str | None = None
    capabilities: dict[str, Any] = {}


class TickPayload(BaseModel):
    terminal_id: str
    symbol: str
    bid: float
    ask: float
    last: float = 0.0
    volume: float = 0.0
    ts: str | None = None


class PollPayload(BaseModel):
    terminal_id: str
    balance: float = 0.0
    equity: float = 0.0
    margin: float = 0.0
    free_margin: float = 0.0
    currency: str = "USD"
    leverage: int = 100
    auth_token: str | None = None


class ReportPayload(BaseModel):
    terminal_id: str
    event_type: str
    payload: dict[str, Any]


@router.post("/register")
async def register_terminal(payload: RegisterPayload):
    """Register MT5 terminal via native WebRequest."""
    registry = get_registry()
    await registry.register(
        terminal_id=payload.terminal_id,
        broker=payload.broker,
        account=str(payload.account),
        symbols=payload.symbols,
        capabilities=payload.capabilities,
        version=payload.version,
    )
    return {"status": "registered", "terminal_id": payload.terminal_id}


@router.post("/tick")
async def ingest_tick(payload: TickPayload):
    """Ingest tick from MT5 via native WebRequest."""
    registry = get_registry()
    await registry.update_tick(
        terminal_id=payload.terminal_id,
        symbol=payload.symbol,
        bid=payload.bid,
        ask=payload.ask,
        last=payload.last,
        volume=payload.volume,
    )
    return {"status": "ok"}


@router.post("/poll")
async def poll_terminal(payload: PollPayload):
    """Heartbeat & command polling for MT5 via native WebRequest."""
    registry = get_registry()
    await registry.touch(payload.terminal_id)
    await registry.update_account(
        terminal_id=payload.terminal_id,
        balance=payload.balance,
        equity=payload.equity,
        margin=payload.margin,
        free_margin=payload.free_margin,
        currency=payload.currency,
        leverage=payload.leverage,
    )
    commands = await registry.pop_commands(payload.terminal_id)
    return {"status": "ok", "commands": commands}


@router.post("/report")
async def execution_report(payload: ReportPayload):
    """Ingest order/position execution reports from MT5."""
    registry = get_registry()
    await registry.handle_report(
        terminal_id=payload.terminal_id,
        event_type=payload.event_type,
        payload=payload.payload,
    )
    return {"status": "ok"}
