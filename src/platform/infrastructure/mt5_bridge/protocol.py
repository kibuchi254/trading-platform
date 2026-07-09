"""MT5 Bridge Protocol — versioned JSON messages exchanged between the backend
Bridge Service and MT5 terminals (via the MQL5 EA).

The protocol is bidirectional over a single WebSocket connection:
- Server → Terminal: `command` messages (place order, subscribe, sync...)
- Terminal → Server: `event` messages (heartbeat, tick, execution report...)

Every message carries:
  - `v`: protocol version (currently 1)
  - `t`: type — see CommandType / EventType enums below
  - `id`: correlation id (uuid4) for matching request ↔ response
  - `ts`: ISO-8601 timestamp
  - `payload`: type-specific dict

The protocol is intentionally transport-agnostic. Today it's carried by
WebSocket; tomorrow it could be gRPC, AMQP, or a FIX-like binary frame.
Only the framing layer changes — the message envelope does not.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

PROTOCOL_VERSION = 1


# ── Direction markers ────────────────────────────────────────────────────────
# Server → Terminal
class CommandType(enum.StrEnum):
    PING = "cmd.ping"
    PLACE_ORDER = "cmd.order.place"
    MODIFY_ORDER = "cmd.order.modify"
    CANCEL_ORDER = "cmd.order.cancel"
    CLOSE_POSITION = "cmd.position.close"
    MODIFY_POSITION = "cmd.position.modify"
    SYNC_POSITIONS = "cmd.position.sync"
    SYNC_ORDERS = "cmd.order.sync"
    SYNC_ACCOUNT = "cmd.account.sync"
    SUBSCRIBE_TICKS = "cmd.ticks.subscribe"
    UNSUBSCRIBE_TICKS = "cmd.ticks.unsubscribe"
    SUBSCRIBE_SYMBOLS = "cmd.symbols.subscribe"
    GET_HISTORY = "cmd.history.get"
    RESTART_EA = "cmd.ea.restart"
    FLATTEN_ALL = "cmd.account.flatten"


# Terminal → Server
class EventType(enum.StrEnum):
    REGISTER = "evt.register"
    HEARTBEAT = "evt.heartbeat"
    TICK = "evt.tick"
    BAR = "evt.bar"  # OHLC update
    ORDER_ACCEPTED = "evt.order.accepted"
    ORDER_REJECTED = "evt.order.rejected"
    ORDER_PARTIAL = "evt.order.partial"
    ORDER_FILLED = "evt.order.filled"
    ORDER_CANCELLED = "evt.order.cancelled"
    POSITION_OPENED = "evt.position.opened"
    POSITION_MODIFIED = "evt.position.modified"
    POSITION_CLOSED = "evt.position.closed"
    ACCOUNT_UPDATE = "evt.account.update"
    SYMBOL_INFO = "evt.symbol.info"
    ERROR = "evt.error"
    LOG = "evt.log"


# ── Envelope ─────────────────────────────────────────────────────────────────


class BridgeMessage(BaseModel):
    """Wire format — both directions."""

    v: int = PROTOCOL_VERSION
    t: str
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    terminal_id: str | None = None
    reply_to: str | None = None  # for responses, echoes the original command id
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = {"use_enum_values": True}


# ── Typed payload helpers (used by both server and EA) ──────────────────────


class RegisterPayload(BaseModel):
    terminal_id: str
    broker: str
    account: str
    version: str | None = None
    symbols: list[str] = Field(default_factory=list)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    auth_token: str  # validated server-side


class HeartbeatPayload(BaseModel):
    terminal_id: str
    server_time: datetime | None = None
    latency_ms: int | None = None


class TickPayload(BaseModel):
    symbol: str
    bid: float
    ask: float
    last: float | None = None
    volume: float | None = None
    ts: datetime


class PlaceOrderPayload(BaseModel):
    client_order_id: str
    symbol: str
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit", "stop", "stop_limit"]
    volume: float
    price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    comment: str | None = None
    magic: int | None = None


class ExecutionReportPayload(BaseModel):
    client_order_id: str
    broker_order_id: str | None = None
    broker_execution_id: str | None = None
    status: Literal["accepted", "rejected", "partial", "filled", "cancelled"]
    filled_volume: float = 0.0
    avg_price: float | None = None
    rejection_reason: str | None = None
    executed_at: datetime


class PositionUpdatePayload(BaseModel):
    broker_position_id: str
    symbol: str
    side: Literal["buy", "sell"]
    volume: float
    open_price: float
    current_price: float
    stop_loss: float | None = None
    take_profit: float | None = None
    swap: float = 0.0
    unrealized_pnl: float = 0.0
    opened_at: datetime


class AccountUpdatePayload(BaseModel):
    balance: float
    equity: float
    margin: float
    free_margin: float
    currency: str = "USD"
    leverage: int = 100


# ── Helper constructors ─────────────────────────────────────────────────────


def command(cmd: CommandType, *, terminal_id: str, payload: dict | None = None) -> BridgeMessage:
    return BridgeMessage(t=cmd.value, terminal_id=terminal_id, payload=payload or {})


def event(evt: EventType, *, terminal_id: str, payload: dict | None = None) -> BridgeMessage:
    return BridgeMessage(t=evt.value, terminal_id=terminal_id, payload=payload or {})


def ack(original: BridgeMessage, *, payload: dict | None = None) -> BridgeMessage:
    """Build a server acknowledgement for a terminal command response."""
    return BridgeMessage(
        t=original.t,
        reply_to=original.id,
        terminal_id=original.terminal_id,
        payload=payload or {},
    )


__all__ = [
    "PROTOCOL_VERSION",
    "AccountUpdatePayload",
    "BridgeMessage",
    "CommandType",
    "EventType",
    "ExecutionReportPayload",
    "HeartbeatPayload",
    "PlaceOrderPayload",
    "PositionUpdatePayload",
    "RegisterPayload",
    "TickPayload",
    "ack",
    "command",
    "event",
]
