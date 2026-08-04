"""Native HTTP Bridge router for MT5 WebRequest (Zero-DLL connection).

MT5 terminals running the zero-DLL BridgeEA connect via HTTP polling instead
of WebSocket: they POST to /register, /poll (heartbeat + account state), /tick,
and /report. This router is the HTTP counterpart of the WS bridge in
`bridge/handlers.py` — it feeds the same event bus so downstream subscribers
(market-data engine, /ws streams, account WS) work identically for both
transport modes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from platform.core.logging import get_logger
from platform.db.models import Account, Terminal
from platform.db.session import db_context
from platform.events.bus import get_event_bus
from platform.events.topics import Topic
from platform.infrastructure.mt5_bridge.command_queue import get_command_queue
from platform.infrastructure.mt5_bridge.protocol import BridgeMessage
from platform.infrastructure.mt5_bridge.registry import TerminalRecord, get_registry
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

router = APIRouter(prefix="/bridge-http", tags=["bridge-http"])
_log = get_logger(__name__)


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
    payload: dict[str, Any] = {}


@router.post("/register")
async def register_terminal(payload: RegisterPayload) -> dict:
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
async def ingest_tick(payload: TickPayload) -> dict:
    """Ingest tick from MT5 via native WebRequest — fan out to the event bus so
    the market-data engine builds candles and /ws/ticks streams live."""
    registry = get_registry()
    await registry.heartbeat(payload.terminal_id)
    bus = get_event_bus()
    await bus.publish(
        Topic.TICKS,
        {
            "terminal_id": payload.terminal_id,
            "symbol": payload.symbol,
            "bid": payload.bid,
            "ask": payload.ask,
            "last": payload.last,
            "volume": payload.volume,
            "ts": payload.ts or datetime.now(UTC).isoformat(),
        },
    )
    return {"status": "ok"}


@router.post("/poll")
async def poll_terminal(payload: PollPayload) -> dict:
    """Heartbeat + account-state ingest + outbound command delivery for HTTP
    terminals. The EA calls this every few seconds with its current balance/
    equity/margin; we cache it, publish an ACCOUNT_UPDATE (so /ws/account
    streams live), best-effort persist to the `accounts` table, and return any
    queued outbound commands for the terminal to execute."""
    registry = get_registry()
    await registry.heartbeat(payload.terminal_id)

    snapshot = {
        "terminal_id": payload.terminal_id,
        "balance": payload.balance,
        "equity": payload.equity,
        "margin": payload.margin,
        "free_margin": payload.free_margin,
        "currency": payload.currency,
        "leverage": payload.leverage,
    }
    await registry.set_account(payload.terminal_id, snapshot)

    bus = get_event_bus()
    await bus.publish(Topic.ACCOUNT_UPDATES, snapshot)

    # Best-effort DB upsert — skip silently if no Terminal row exists yet.
    try:
        await _persist_account(payload.terminal_id, snapshot)
    except Exception:
        _log.warning("account_persist_failed", terminal_id=payload.terminal_id, exc_info=True)

    # Drain any outbound commands queued by BridgeClient for this terminal.
    commands = await registry.drain_outbox(payload.terminal_id)
    return {
        "status": "ok",
        "commands": [c.model_dump(mode="json") for c in commands],
    }


@router.post("/report")
async def execution_report(payload: ReportPayload) -> dict:
    """Ingest order/position execution reports from MT5.

    Resolves any pending command awaiting this report (correlated by
    client_order_id for HTTP terminals, which don't echo the command id) and
    fans the event out to the bus so the application layer can update its
    aggregates.
    """
    registry = get_registry()
    await registry.heartbeat(payload.terminal_id)

    et = payload.event_type
    p = payload.payload
    client_order_id = p.get("client_order_id")
    broker_position_id = p.get("broker_position_id")

    bus = get_event_bus()
    queue = get_command_queue()

    if et.startswith("evt.order."):
        evt = {
            "terminal_id": payload.terminal_id,
            "client_order_id": client_order_id,
            "broker_order_id": p.get("broker_order_id"),
            "broker_execution_id": p.get("broker_execution_id"),
            "status": p.get("status"),
            "filled_volume": p.get("filled_volume", 0),
            "avg_price": p.get("avg_price"),
            "rejection_reason": p.get("rejection_reason"),
            "executed_at": p.get("executed_at") or datetime.now(UTC).isoformat(),
        }
        await bus.publish(Topic.EXECUTION_REPORTS, evt)
        if client_order_id:
            await queue.resolve_by_correlation(
                payload.terminal_id, str(client_order_id), BridgeMessage(t=et, payload=p)
            )
    elif et.startswith("evt.position."):
        evt = {
            "terminal_id": payload.terminal_id,
            "broker_position_id": broker_position_id,
            "symbol": p.get("symbol"),
            "side": p.get("side"),
            "volume": p.get("volume"),
            "open_price": p.get("open_price"),
            "current_price": p.get("current_price"),
            "stop_loss": p.get("stop_loss"),
            "take_profit": p.get("take_profit"),
            "swap": p.get("swap", 0),
            "unrealized_pnl": p.get("unrealized_pnl", 0),
            "opened_at": p.get("opened_at") or datetime.now(UTC).isoformat(),
        }
        await bus.publish(Topic.POSITION_UPDATES, evt)

    return {"status": "ok"}


async def _persist_account(terminal_id: str, snapshot: dict) -> None:
    """Upsert the accounts row for a terminal (best-effort)."""
    async with db_context() as db:
        terminal = (
            await db.execute(select(Terminal).where(Terminal.terminal_id == terminal_id))
        ).scalar_one_or_none()
        if terminal is None:
            return  # No DB Terminal row — registry cache is the source of truth.

        acct = (
            await db.execute(select(Account).where(Account.terminal_id == terminal.id))
        ).scalar_one_or_none()
        if acct is None:
            acct = Account(
                org_id=terminal.org_id,
                terminal_id=terminal.id,
                broker_login=terminal.broker_account,
                currency=snapshot.get("currency", "USD"),
                leverage=int(snapshot.get("leverage", 100)),
            )
            db.add(acct)
        acct.balance = float(snapshot.get("balance", 0))
        acct.equity = float(snapshot.get("equity", 0))
        acct.margin = float(snapshot.get("margin", 0))
        acct.free_margin = float(snapshot.get("free_margin", 0))
        acct.currency = snapshot.get("currency", acct.currency)
        acct.leverage = int(snapshot.get("leverage", acct.leverage))
        acct.last_synced_at = datetime.now(UTC)
        await db.commit()
