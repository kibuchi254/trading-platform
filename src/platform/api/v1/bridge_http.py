"""Native HTTP Bridge router for MT5 WebRequest (Zero-DLL connection)."""

from __future__ import annotations

from platform.infrastructure.mt5_bridge.registry import TerminalRecord, get_registry
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/bridge-http", tags=["bridge-http"])


class HttpSession:
    """Mock session for native HTTP WebRequest connections."""

    def __init__(self, session_id: str) -> None:
        self.id = session_id

    async def close(self, code: int = 1000, reason: str = "") -> None:
        pass


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
    record = TerminalRecord(
        terminal_id=payload.terminal_id,
        broker=payload.broker or "Exness",
        account=str(payload.account),
        version=payload.version,
        symbols=payload.symbols,
        capabilities=payload.capabilities,
        session=HttpSession(session_id=f"http-{payload.terminal_id}"),
    )
    await registry.register(record)
    return {"status": "registered", "terminal_id": payload.terminal_id}


@router.post("/tick")
async def ingest_tick(payload: TickPayload):
    """Ingest tick from MT5 via native WebRequest."""
    registry = get_registry()
    rec = await registry.get(payload.terminal_id)
    if rec:
        await registry.heartbeat(payload.terminal_id)
    return {"status": "ok"}


@router.post("/poll")
async def poll_terminal(payload: PollPayload):
    """Heartbeat & command polling for MT5 via native WebRequest."""
    registry = get_registry()
    await registry.heartbeat(payload.terminal_id)
    return {"status": "ok"}


@router.post("/report")
async def execution_report(payload: ReportPayload):
    """Ingest order/position execution reports from MT5."""
    registry = get_registry()
    rec = await registry.get(payload.terminal_id)
    if rec:
        await registry.heartbeat(payload.terminal_id)
    return {"status": "ok"}
