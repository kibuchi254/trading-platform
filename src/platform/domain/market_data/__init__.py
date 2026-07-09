"""Market Data bounded context — Tick, OHLCBar, SymbolInfo, AggregatedBar, ReplaySession.

Pure-Python domain layer for market-data ingestion & bar aggregation. The
aggregates here mirror what `platform/db/models/__init__.py` persists but
contain no SQLAlchemy. Heavy ingestion pipelines (TimescaleDB hypertables, etc.)
operate on these aggregates via repositories in `infrastructure/`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timezone
from enum import StrEnum
from platform.core.exceptions import DomainError
from platform.domain.shared import (
    AggregateRoot,
    DomainEvent,
    Timeframe,
    ValueObject,
)
from typing import Tuple
from uuid import UUID, uuid4

# Re-export Timeframe so callers can `from platform.domain.market_data import Timeframe`.
__all__ = [
    "AggregatedBar",
    "OHLCBar",
    "ReplaySession",
    "ReplayStatus",
    "SymbolInfo",
    "Tick",
    "Timeframe",
    "TimeframeBucket",
]


# ── Value objects ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Tick(ValueObject):
    """A frozen bid/ask/last/volume snapshot at an instant in time.

    `bid` must be ≤ `ask`; both must be positive. `last` and `volume` may be
    None for symbols that do not report them (e.g. pure FX feeds).
    """

    symbol: str
    bid: float
    ask: float
    last: float | None = None
    volume: float | None = None
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.bid <= 0 or self.ask <= 0:
            raise DomainError("bid/ask must be positive")
        if self.bid > self.ask:
            raise DomainError(f"bid {self.bid} > ask {self.ask}")

    @property
    def mid(self) -> float:
        """Mid-market price = (bid + ask) / 2."""
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> float:
        """Absolute spread in price units (ask - bid)."""
        return self.ask - self.bid

    @property
    def spread_pct(self) -> float:
        """Spread as a fraction of mid — useful for cost comparison across symbols."""
        return self.spread / self.mid


@dataclass(frozen=True)
class SymbolInfo(ValueObject):
    """Static metadata for a tradeable symbol.

    Pure data — no behaviour beyond the `point` derivation. Used by sizing,
    spread-protection, and pip/price conversion logic throughout the platform.
    """

    name: str
    description: str = ""
    category: str = "fx"
    digits: int = 5
    contract_size: float = 1.0
    volume_min: float = 0.01
    volume_step: float = 0.01
    volume_max: float = 100.0
    margin_rate: float = 0.01
    swap_long: float = 0.0
    swap_short: float = 0.0

    def __post_init__(self) -> None:
        if self.digits < 0:
            raise DomainError("digits cannot be negative")
        if self.volume_step <= 0:
            raise DomainError("volume_step must be positive")

    @property
    def point(self) -> float:
        """Smallest representable price increment = 10^(-digits)."""
        return 10 ** (-self.digits)

    def normalize_volume(self, volume: float) -> float:
        """Snap a raw volume onto the step grid, clamped to [min, max]."""
        steps = round(volume / self.volume_step)
        v = steps * self.volume_step
        return max(self.volume_min, min(self.volume_max, v))


@dataclass(frozen=True)
class TimeframeBucket(ValueObject):
    """A (symbol, timeframe, bucket_start_ts) tuple — the identity of a bar."""

    symbol: str
    timeframe: Timeframe
    bucket_start: datetime


# ── Domain events ───────────────────────────────────────────────────────────


@dataclass(kw_only=True)
class BarFormed(DomainEvent):
    bar_id: UUID
    symbol: str
    timeframe: str
    ts: datetime


@dataclass(kw_only=True)
class BarClosed(DomainEvent):
    bar_id: UUID
    symbol: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    tick_count: int


@dataclass(kw_only=True)
class ReplayStarted(DomainEvent):
    session_id: UUID
    symbol: str


@dataclass(kw_only=True)
class ReplayCompleted(DomainEvent):
    session_id: UUID


# ── OHLCBar aggregate ───────────────────────────────────────────────────────


@dataclass(kw_only=True)
class OHLCBar(AggregateRoot):
    """A single OHLC bar being built from incoming ticks.

    The first `update()` call sets open=high=low=close=price and emits
    `BarFormed`. Subsequent calls extend high/low and overwrite close. `close()`
    freezes the bar and emits `BarClosed`.
    """

    symbol: str
    timeframe: Timeframe
    ts: datetime
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    is_closed: bool = False
    tick_count: int = 0

    def update(self, price: float, volume: float = 0.0) -> None:
        """Incorporate a tick into the bar. Errors if the bar is already closed."""
        if self.is_closed:
            raise DomainError("Cannot update a closed bar")
        if price <= 0:
            raise DomainError("price must be positive")
        if self.tick_count == 0:
            self.open = price
            self.high = price
            self.low = price
            self.record_event(
                BarFormed(
                    bar_id=self.id,
                    symbol=self.symbol,
                    timeframe=self.timeframe.code,
                    ts=self.ts,
                )
            )
        else:
            self.high = max(self.high, price)
            self.low = min(self.low, price)
        self.close = price
        self.volume += volume
        self.tick_count += 1

    def close_bar(self) -> None:
        """Freeze the bar (spec: `close()`). Renamed to avoid clobbering the
        `close` price field — Python cannot host a field and a method with
        the same name. Mirrors the existing `Candle.close_bar()` convention.

        Errors on empty bars — closeable bars have ≥1 tick.
        """
        if self.is_closed:
            raise DomainError("Bar already closed")
        if self.tick_count == 0:
            raise DomainError("Cannot close an empty bar")
        self.is_closed = True
        self.record_event(
            BarClosed(
                bar_id=self.id,
                symbol=self.symbol,
                timeframe=self.timeframe.code,
                open=self.open,
                high=self.high,
                low=self.low,
                close=self.close,
                volume=self.volume,
                tick_count=self.tick_count,
            )
        )


# ── AggregatedBar aggregate ─────────────────────────────────────────────────


@dataclass(kw_only=True)
class AggregatedBar(AggregateRoot):
    """Multi-timeframe bar aggregator — wraps the current & last-closed bar
    for a single (symbol, timeframe).

    `ingest(tick)` returns `(current_bar, closed_bar_or_None)`. When a tick
    falls outside the current bucket the bar is closed, archived to
    `last_closed_bar`, and a fresh bar is opened.
    """

    bucket: TimeframeBucket
    current_bar: OHLCBar | None = None
    last_closed_bar: OHLCBar | None = None

    def _bucket_start_for(self, ts: datetime) -> datetime:
        """Floor `ts` to the start of its timeframe bucket."""
        seconds = self.bucket.timeframe.seconds
        epoch = int(ts.timestamp())
        floored = (epoch // seconds) * seconds
        return datetime.fromtimestamp(floored, tz=ts.tzinfo or UTC)

    def ingest(self, tick: Tick) -> tuple[OHLCBar, OHLCBar | None]:
        """Feed a tick into the aggregator.

        Returns `(current_bar_after_update, just_closed_bar_or_None)`. The
        closed bar is returned only on the tick that triggers a bucket roll.
        """
        if tick.symbol != self.bucket.symbol:
            raise DomainError(f"Tick symbol {tick.symbol} != bucket symbol {self.bucket.symbol}")
        bucket_start = self._bucket_start_for(tick.ts)
        closed: OHLCBar | None = None

        if self.current_bar is None or bucket_start != self.bucket.bucket_start:
            # Roll the bucket: close the old bar (if any) and start a new one.
            if self.current_bar is not None and not self.current_bar.is_closed:
                self.current_bar.close_bar()
                self.last_closed_bar = self.current_bar
                closed = self.last_closed_bar
            self.bucket = TimeframeBucket(
                symbol=self.bucket.symbol,
                timeframe=self.bucket.timeframe,
                bucket_start=bucket_start,
            )
            self.current_bar = OHLCBar(
                symbol=self.bucket.symbol,
                timeframe=self.bucket.timeframe,
                ts=bucket_start,
            )

        self.current_bar.update(tick.mid, tick.volume or 0.0)
        return self.current_bar, closed


# ── ReplaySession aggregate ─────────────────────────────────────────────────


class ReplayStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"


@dataclass(kw_only=True)
class ReplaySession(AggregateRoot):
    """A historical-data replay session for backtests or visualisations.

    Lifecycle: PENDING → RUNNING ↔ PAUSED → COMPLETED. `current_position` is
    a tick offset into the [start, end] window.
    """

    session_id: UUID = field(default_factory=uuid4)
    symbol: str = ""
    timeframe: Timeframe | None = None
    start: datetime = field(default_factory=lambda: datetime.now(UTC))
    end: datetime = field(default_factory=lambda: datetime.now(UTC))
    speed_multiplier: float = 1.0
    current_position: int = 0
    status: ReplayStatus = ReplayStatus.PENDING

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise DomainError("end must be >= start")
        if self.speed_multiplier <= 0:
            raise DomainError("speed_multiplier must be positive")

    def start_session(self) -> None:
        """Begin playback. Errors unless currently PENDING."""
        if self.status != ReplayStatus.PENDING:
            raise DomainError(f"Cannot start session in status {self.status}")
        self.status = ReplayStatus.RUNNING
        self.record_event(ReplayStarted(session_id=self.session_id, symbol=self.symbol))

    def pause(self) -> None:
        if self.status != ReplayStatus.RUNNING:
            raise DomainError(f"Cannot pause session in status {self.status}")
        self.status = ReplayStatus.PAUSED

    def resume(self) -> None:
        if self.status != ReplayStatus.PAUSED:
            raise DomainError(f"Cannot resume session in status {self.status}")
        self.status = ReplayStatus.RUNNING

    def advance(self, n_ticks: int = 1) -> None:
        """Move the playback cursor forward by `n_ticks`. Auto-completes at end."""
        if self.status != ReplayStatus.RUNNING:
            raise DomainError(f"Cannot advance session in status {self.status}")
        if n_ticks <= 0:
            raise DomainError("n_ticks must be positive")
        self.current_position += n_ticks

    def complete(self) -> None:
        """Mark the replay as finished."""
        if self.status == ReplayStatus.COMPLETED:
            return
        self.status = ReplayStatus.COMPLETED
        self.record_event(ReplayCompleted(session_id=self.session_id))
