"""Market Data engine — tick ingestion, OHLC aggregation, replay, multi-TF cache."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from platform.core.logging import get_logger
from platform.events.bus import get_event_bus
from platform.events.topics import Topic

_log = get_logger(__name__)


@dataclass
class OHLCBar:
    symbol: str
    timeframe: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    is_closed: bool = False
    tick_count: int = 0

    def update(self, price: float, volume: float = 0) -> None:
        if self.tick_count == 0:
            self.open = price
        self.high = max(self.high, price)
        self.low = min(self.low, price) if self.low > 0 else price
        self.close = price
        self.volume += volume
        self.tick_count += 1


@dataclass
class TimeframeBucket:
    symbol: str
    timeframe: str
    seconds: int
    current_bar: OHLCBar | None = None

    def ingest(self, price: float, volume: float, ts: datetime) -> tuple[OHLCBar, OHLCBar | None]:
        """Returns (current_bar, just_closed_bar_or_None)."""
        bucket_ts = datetime.fromtimestamp(
            (int(ts.timestamp()) // self.seconds) * self.seconds, tz=timezone.utc
        )
        closed: OHLCBar | None = None
        if self.current_bar is None or self.current_bar.ts != bucket_ts:
            if self.current_bar is not None:
                self.current_bar.is_closed = True
                closed = self.current_bar
            self.current_bar = OHLCBar(
                symbol=self.symbol, timeframe=self.timeframe, ts=bucket_ts,
                open=price, high=price, low=price, close=price,
                volume=volume, tick_count=1,
            )
        else:
            self.current_bar.update(price, volume)
        return self.current_bar, closed


class MarketDataEngine:
    """Subscribes to TICKS, aggregates OHLC for all configured timeframes,
    publishes closed bars back to the bus for strategies + AI to consume."""

    TIMEFRAMES = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800,
                  "H1": 3600, "H4": 14400, "D1": 86400}

    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str], TimeframeBucket] = {}

    async def start(self) -> None:
        bus = get_event_bus()
        bus.subscribe(Topic.TICKS, self._on_tick)
        _log.info("market_data_engine_started")

    def _get_bucket(self, symbol: str, tf: str) -> TimeframeBucket:
        key = (symbol, tf)
        if key not in self._buckets:
            self._buckets[key] = TimeframeBucket(
                symbol=symbol, timeframe=tf, seconds=self.TIMEFRAMES[tf]
            )
        return self._buckets[key]

    async def _on_tick(self, payload: dict[str, Any]) -> None:
        symbol = payload["symbol"]
        bid = float(payload["bid"])
        ask = float(payload["ask"])
        last = float(payload.get("last") or (bid + ask) / 2)
        volume = float(payload.get("volume") or 0)
        ts = datetime.fromisoformat(payload["ts"])

        bus = get_event_bus()
        for tf in self.TIMEFRAMES:
            bucket = self._get_bucket(symbol, tf)
            _, closed = bucket.ingest(last, volume, ts)
            if closed is not None:
                await bus.publish(
                    Topic.TICKS,  # reuse — subscribers filter by `bar` key
                    {
                        "type": "bar_closed", "symbol": symbol, "timeframe": tf,
                        "ts": closed.ts.isoformat(), "open": closed.open,
                        "high": closed.high, "low": closed.low, "close": closed.close,
                        "volume": closed.volume, "is_closed": True,
                    },
                )


_engine: MarketDataEngine | None = None


def get_market_data_engine() -> MarketDataEngine:
    global _engine
    if _engine is None:
        _engine = MarketDataEngine()
    return _engine
