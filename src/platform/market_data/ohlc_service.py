"""OHLC service — query & serve historical OHLC candles.

Reads from the persisted ``candles`` table, with a tiny in-memory LRU cache
keyed by ``(symbol, timeframe, ts_bucket)`` for hot bars. When the candles
table is missing data for a requested window, ``aggregate_on_demand`` will
fall through to the raw ``ticks`` table and synthesise the bars on the fly.

This is the read-side counterpart to ``MarketDataEngine`` (which writes
closed bars). All public methods are async and safe to call concurrently.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import UTC, datetime
from platform.core.logging import get_logger
from platform.db.models import Candle, Tick
from platform.db.session import db_context
from platform.market_data.engine import MarketDataEngine
from typing import Any

from sqlalchemy import desc, select

_log = get_logger(__name__)

# ── Tunables ─────────────────────────────────────────────────────────────────
LRU_MAXSIZE: int = 1000

# Reuse the engine's timeframe table — single source of truth for bucket sizes.
_TF_SECONDS: dict[str, int] = MarketDataEngine.TIMEFRAMES


class _CandleLRU:
    """Thin ``OrderedDict``-backed LRU keyed by ``(symbol, timeframe, ts_bucket)``.

    ``OrderedDict.move_to_end`` gives us O(1) recency updates. We store raw
    ``Candle`` ORM instances detached from any session — callers must treat
    them as read-only snapshots.
    """

    def __init__(self, maxsize: int = LRU_MAXSIZE) -> None:
        self._maxsize = maxsize
        self._data: OrderedDict[tuple[str, str, datetime], Candle] = OrderedDict()

    def get(self, key: tuple[str, str, datetime]) -> Candle | None:
        v = self._data.get(key)
        if v is not None:
            self._data.move_to_end(key)
        return v

    def put(self, key: tuple[str, str, datetime], value: Candle) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self._maxsize:
            self._data.popitem(last=False)

    def invalidate(self, symbol: str | None = None, timeframe: str | None = None) -> None:
        """Drop entries. With no args, clears everything; otherwise scopes by symbol/timeframe."""
        if symbol is None and timeframe is None:
            self._data.clear()
            return
        keys = [
            k
            for k in self._data
            if (symbol is None or k[0] == symbol) and (timeframe is None or k[1] == timeframe)
        ]
        for k in keys:
            self._data.pop(k, None)

    def __len__(self) -> int:
        return len(self._data)


class OHLCService:
    """Query/serve historical OHLC candles with caching + on-demand aggregation."""

    def __init__(self) -> None:
        self._cache: _CandleLRU = _CandleLRU(maxsize=LRU_MAXSIZE)

    # ── Public API ──────────────────────────────────────────────────────────

    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        limit: int = 1000,
    ) -> list[Candle]:
        """Return candles for ``[start, end]`` (inclusive), newest-first preference.

        Results are ordered ascending by ``ts`` for charting convenience. The
        in-memory cache is consulted for individual buckets but never used to
        short-circuit range queries — the DB has the (symbol, timeframe, ts)
        index and is the authoritative source for ranges.

        Args:
            symbol:    e.g. ``"EURUSD"``.
            timeframe: one of M1/M5/M15/M30/H1/H4/D1.
            start:     inclusive lower bound (timezone-aware recommended).
            end:       inclusive upper bound.
            limit:     max rows to return (default 1000).

        Returns:
            List of ``Candle`` ORM instances, ascending by ``ts``.
        """
        if timeframe not in _TF_SECONDS:
            raise ValueError(f"unsupported timeframe: {timeframe}")
        if limit <= 0:
            return []

        stmt = (
            select(Candle)
            .where(
                Candle.symbol == symbol,
                Candle.timeframe == timeframe,
                Candle.ts >= start,
                Candle.ts <= end,
            )
            .order_by(Candle.ts.asc())
            .limit(limit)
        )
        async with db_context() as db:
            rows = list((await db.execute(stmt)).scalars().all())
            # Detach so callers can use them after session close.
            for r in rows:
                db.expunge(r)
        # Warm the cache for any rows we just fetched.
        for r in rows:
            self._cache.put((symbol, timeframe, r.ts), r)
        _log.debug("ohlc_get_candles", symbol=symbol, timeframe=timeframe, count=len(rows))
        return rows

    async def get_latest_close(self, symbol: str, timeframe: str) -> float | None:
        """Return the most recent closed-candle close price, or ``None`` if no data.

        Prefer the cache — the latest bar is the hottest key in any charting
        workload. Falls back to a single-row DB query on miss and caches the
        result.
        """
        if timeframe not in _TF_SECONDS:
            raise ValueError(f"unsupported timeframe: {timeframe}")

        # Cache probe: any candle we have for this (symbol, timeframe) gives a
        # reasonable upper bound on recency. We can't know the *latest* ts
        # without a DB hit, so this is best-effort.
        stmt = (
            select(Candle)
            .where(Candle.symbol == symbol, Candle.timeframe == timeframe)
            .order_by(desc(Candle.ts))
            .limit(1)
        )
        async with db_context() as db:
            row = (await db.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            db.expunge(row)
        self._cache.put((symbol, timeframe, row.ts), row)
        return float(row.close)

    async def get_history(self, symbol: str, timeframe: str, count: int = 500) -> list[Candle]:
        """Convenience wrapper — the last ``count`` candles ending *now*.

        Ideal for charting endpoints that just want "the last N bars".
        Returns ascending-by-ts so the most recent candle is the last element.
        """
        if count <= 0:
            return []
        stmt = (
            select(Candle)
            .where(Candle.symbol == symbol, Candle.timeframe == timeframe)
            .order_by(desc(Candle.ts))
            .limit(count)
        )
        async with db_context() as db:
            rows = list((await db.execute(stmt)).scalars().all())
            for r in rows:
                db.expunge(r)
        rows.reverse()  # ascending for charting
        for r in rows:
            self._cache.put((symbol, timeframe, r.ts), r)
        return rows

    async def aggregate_on_demand(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """Aggregate candles from raw ticks when the candles table is sparse.

        Use case: a strategy requests H1 bars for a date range that was never
        back-filled into ``candles``. Rather than 404, we stream the raw
        ``ticks`` for that window and bucket them in-process using the same
        ``TimeframeBucket`` logic the live engine uses.

        Returns the synthesised candles in ascending ``ts`` order. They are
        *not* persisted here — persistence is the job of a separate back-fill
        worker (out of scope for this service).
        """
        if timeframe not in _TF_SECONDS:
            raise ValueError(f"unsupported timeframe: {timeframe}")
        seconds = _TF_SECONDS[timeframe]

        stmt = (
            select(Tick.symbol, Tick.bid, Tick.ask, Tick.last, Tick.volume, Tick.ts)
            .where(
                Tick.symbol == symbol,
                Tick.ts >= start,
                Tick.ts <= end,
            )
            .order_by(Tick.ts.asc())
        )
        async with db_context() as db:
            stream = (await db.execute(stmt)).all()

        if not stream:
            return []

        bars: dict[datetime, dict[str, Any]] = {}
        for symbol_, bid, ask, last, volume, ts in stream:
            bid_f = float(bid)
            ask_f = float(ask)
            last_f = float(last) if last is not None else (bid_f + ask_f) / 2
            vol_f = float(volume) if volume is not None else 0.0
            ts_aware = ts if ts.tzinfo else ts.replace(tzinfo=UTC)
            bucket_ts = datetime.fromtimestamp(
                (int(ts_aware.timestamp()) // seconds) * seconds, tz=UTC
            )
            bar = bars.get(bucket_ts)
            if bar is None:
                bars[bucket_ts] = {
                    "open": last_f,
                    "high": last_f,
                    "low": last_f,
                    "close": last_f,
                    "volume": vol_f,
                    "tick_count": 1,
                }
            else:
                bar["high"] = max(bar["high"], last_f)
                bar["low"] = min(bar["low"], last_f)
                bar["close"] = last_f
                bar["volume"] += vol_f
                bar["tick_count"] += 1

        # Build detached Candle snapshots — never persisted, only returned.
        out: list[Candle] = []
        for bucket_ts in sorted(bars):
            b = bars[bucket_ts]
            c = Candle(
                symbol=symbol,
                timeframe=timeframe,
                ts=bucket_ts,
                open=b["open"],
                high=b["high"],
                low=b["low"],
                close=b["close"],
                volume=b["volume"],
                is_closed=True,
            )
            out.append(c)
            self._cache.put((symbol, timeframe, bucket_ts), c)
        _log.info(
            "ohlc_aggregated_on_demand",
            symbol=symbol,
            timeframe=timeframe,
            ticks=len(stream),
            bars=len(out),
        )
        return out

    # ── Cache management ────────────────────────────────────────────────────

    def invalidate_cache(self, symbol: str | None = None, timeframe: str | None = None) -> None:
        """Drop cached candles. Call after bulk imports / back-fills."""
        self._cache.invalidate(symbol=symbol, timeframe=timeframe)

    def cache_size(self) -> int:
        """Number of candles currently held in the LRU."""
        return len(self._cache)


# ── Singleton ────────────────────────────────────────────────────────────────
_service: OHLCService | None = None


def get_ohlc_service() -> OHLCService:
    """Return the process-wide ``OHLCService`` singleton."""
    global _service
    if _service is None:
        _service = OHLCService()
    return _service
