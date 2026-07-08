"""Execution adapter abstraction.

The platform never assumes MT5. Every execution venue implements `ExecutionAdapter`.
Adding a new broker/exchange = implementing this interface. No core code changes.

The MT5 Bridge is one such adapter. Other examples:
- PaperBrokerAdapter: simulates fills for backtesting / paper trading
- FixAdapter: FIX 4.4 / 5.0 broker connectivity
- CryptoExchangeAdapter: REST + WebSocket to Binance/Bybit/OKX
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel


class OrderRequest(BaseModel):
    client_order_id: str
    symbol: str
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit", "stop", "stop_limit"]
    volume: float
    price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    comment: str | None = None


class ExecutionReport(BaseModel):
    client_order_id: str
    broker_order_id: str | None = None
    broker_execution_id: str | None = None
    status: Literal["accepted", "rejected", "partial", "filled", "cancelled"]
    filled_volume: float = 0.0
    avg_price: float | None = None
    rejection_reason: str | None = None
    executed_at: datetime


class PositionSnapshot(BaseModel):
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


class AccountSnapshot(BaseModel):
    balance: float
    equity: float
    margin: float
    free_margin: float
    currency: str = "USD"
    leverage: int = 100


class ExecutionAdapter(abc.ABC):
    """Every execution venue implements this. Pure interface — no implementation."""

    adapter_kind: str = "abstract"

    @abc.abstractmethod
    async def connect(self) -> None: ...

    @abc.abstractmethod
    async def disconnect(self) -> None: ...

    @abc.abstractmethod
    async def place_order(self, req: OrderRequest) -> ExecutionReport: ...

    @abc.abstractmethod
    async def cancel_order(self, broker_order_id: str) -> ExecutionReport: ...

    @abc.abstractmethod
    async def close_position(self, broker_position_id: str, volume: float | None = None) -> ExecutionReport: ...

    @abc.abstractmethod
    async def modify_position(self, broker_position_id: str, *,
                              stop_loss: float | None = None,
                              take_profit: float | None = None) -> ExecutionReport: ...

    @abc.abstractmethod
    async def sync_positions(self) -> list[PositionSnapshot]: ...

    @abc.abstractmethod
    async def sync_account(self) -> AccountSnapshot: ...

    @abc.abstractmethod
    async def subscribe_ticks(self, symbols: list[str]) -> None: ...

    @abc.abstractmethod
    async def get_history(self, *, symbol: str, timeframe: str,
                          start: datetime, end: datetime) -> list[dict[str, Any]]: ...
