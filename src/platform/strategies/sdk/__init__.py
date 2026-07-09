"""Strategy SDK — base class every strategy implements.

A strategy is a pure function: (market_data, context) -> Signal | None.
It has no DB access, no HTTP, no side effects. The orchestrator invokes it
on every new bar/tick and feeds signals to the application layer.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class Signal(BaseModel):
    """A trading signal — what the strategy wants to do."""

    symbol: str
    side: str  # buy | sell
    strength: float = 0.0  # 0.0 - 1.0
    suggested_volume: float | None = None
    suggested_stop_loss: float | None = None
    suggested_take_profit: float | None = None
    meta: dict[str, Any] = {}


class Bar(BaseModel):
    symbol: str
    timeframe: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    is_closed: bool = False


class Tick(BaseModel):
    symbol: str
    bid: float
    ask: float
    last: float | None = None
    volume: float | None = None
    ts: datetime


@dataclass
class StrategyContext:
    """Per-strategy runtime state + services the SDK can call."""

    org_id: UUID
    terminal_id: str
    strategy_id: UUID
    config: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)  # strategy-local scratchpad


class Strategy(abc.ABC):
    """Base class. Subclass and implement `on_bar` and/or `on_tick`."""

    name: str = "abstract"
    version: str = "1.0.0"
    default_config: dict[str, Any] = {}

    @abc.abstractmethod
    async def on_bar(self, bar: Bar, ctx: StrategyContext) -> Signal | None:
        """Called on every closed bar for subscribed symbols/timeframes."""

    async def on_tick(self, tick: Tick, ctx: StrategyContext) -> Signal | None:
        """Optional — override for tick-driven strategies."""
        return None

    async def on_start(self, ctx: StrategyContext) -> None:
        """Called once when the strategy is activated."""

    async def on_stop(self, ctx: StrategyContext) -> None:
        """Called once when the strategy is deactivated."""


# ── Registry ──────────────────────────────────────────────────────────────


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, type[Strategy]] = {}

    def register(self, cls: type[Strategy]) -> type[Strategy]:
        if not issubclass(cls, Strategy):
            raise TypeError("Must subclass Strategy")
        self._strategies[cls.name] = cls
        return cls

    def create(self, name: str, config: dict) -> Strategy:
        cls = self._strategies.get(name)
        if cls is None:
            raise KeyError(f"Unknown strategy: {name}")
        merged = {**cls.default_config, **config}
        # Pass config to __init__ if it accepts it
        try:
            return cls(**merged)  # type: ignore[arg-type]
        except TypeError:
            return cls()


_registry = StrategyRegistry()


def get_strategy_registry() -> StrategyRegistry:
    return _registry


def strategy(cls: type[Strategy]) -> type[Strategy]:
    """Decorator: register a strategy class."""
    get_strategy_registry().register(cls)
    return cls
