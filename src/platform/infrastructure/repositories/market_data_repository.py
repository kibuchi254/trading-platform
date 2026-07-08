"""MarketDataRepository — high-throughput persistence for Tick + Candle rows.

Tick ingestion is the hottest write path in the platform (thousands per second
per terminal). `add_ticks_bulk` uses PostgreSQL batch INSERT via SQLAlchemy's
`insert(...).values([...])` to amortise round-trips. Candle persistence uses
`ON CONFLICT (...) DO UPDATE` so partial bars can be upserted as new ticks
extend them.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from platform.db.models import Candle as CandleModel, Tick as TickModel
from platform.domain.market_data import OHLCBar, Tick
from platform.domain.shared import Timeframe


class MarketDataRepository:
    """Async repository for Tick + Candle rows."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Conversions ─────────────────────────────────────────────────────────

    @staticmethod
    def tick_to_orm(t: Tick, terminal_id: UUID) -> TickModel:
        return TickModel(
            terminal_id=terminal_id, symbol=t.symbol, bid=t.bid, ask=t.ask,
            last=t.last, volume=t.volume, ts=t.ts,
        )

    @staticmethod
    def tick_from_orm(m: TickModel) -> Tick:
        return Tick(
            symbol=m.symbol, bid=float(m.bid), ask=float(m.ask),
            last=float(m.last) if m.last is not None else None,
            volume=float(m.volume) if m.volume is not None else None, ts=m.ts,
        )

    @staticmethod
    def candle_to_orm(
        bar: OHLCBar, terminal_id: UUID, *, volume: float | None = None,
    ) -> CandleModel:
        return CandleModel(
            terminal_id=terminal_id, symbol=bar.symbol, timeframe=bar.timeframe.code,
            ts=bar.ts, open=bar.open, high=bar.high, low=bar.low, close=bar.close,
            volume=volume if volume is not None else bar.volume, is_closed=bar.is_closed,
        )

    @staticmethod
    def candle_from_orm(m: CandleModel) -> OHLCBar:
        return OHLCBar(
            symbol=m.symbol, timeframe=Timeframe(code=m.timeframe), ts=m.ts,
            open=float(m.open), high=float(m.high), low=float(m.low),
            close=float(m.close), volume=float(m.volume or 0), is_closed=bool(m.is_closed),
        )

    # ── Tick writes ─────────────────────────────────────────────────────────

    async def add_tick(self, tick: Tick, terminal_id: UUID) -> Tick:
        self.db.add(self.tick_to_orm(tick, terminal_id))
        await self.db.flush()
        return tick

    async def add_ticks_bulk(
        self, ticks: list[Tick], terminal_id: UUID,
    ) -> int:
        """Batch-insert ticks. Returns number of rows queued."""
        if not ticks:
            return 0
        rows = [{"terminal_id": terminal_id, "symbol": t.symbol, "bid": t.bid,
                 "ask": t.ask, "last": t.last, "volume": t.volume, "ts": t.ts}
                for t in ticks]
        await self.db.execute(pg_insert(TickModel).values(rows))
        await self.db.flush()
        return len(rows)

    # ── Tick reads ──────────────────────────────────────────────────────────

    async def get_recent_ticks(self, symbol: str, *, limit: int = 100) -> list[Tick]:
        stmt = select(TickModel).where(TickModel.symbol == symbol).order_by(
            TickModel.ts.desc(),
        ).limit(limit)
        rows = (await self.db.execute(stmt)).scalars().all()
        return [self.tick_from_orm(r) for r in reversed(rows)]  # ascending order

    async def get_ticks_range(
        self, symbol: str, start: datetime, end: datetime,
    ) -> list[Tick]:
        stmt = select(TickModel).where(
            TickModel.symbol == symbol, TickModel.ts >= start, TickModel.ts <= end,
        ).order_by(TickModel.ts.asc())
        return [self.tick_from_orm(r) for r in (await self.db.execute(stmt)).scalars().all()]

    # ── Candle writes ───────────────────────────────────────────────────────

    async def add_candle(
        self, bar: OHLCBar, terminal_id: UUID, *, volume: float | None = None,
    ) -> OHLCBar:
        self.db.add(self.candle_to_orm(bar, terminal_id, volume=volume))
        await self.db.flush()
        return bar

    async def upsert_candle(
        self, bar: OHLCBar, terminal_id: UUID, *, volume: float | None = None,
    ) -> OHLCBar:
        """Insert-or-update on (terminal_id, symbol, timeframe, ts).

        Used when a new tick extends an in-progress bar — high/low/close
        columns get refreshed."""
        vol = volume if volume is not None else bar.volume
        stmt = pg_insert(CandleModel).values(
            terminal_id=terminal_id, symbol=bar.symbol, timeframe=bar.timeframe.code,
            ts=bar.ts, open=bar.open, high=bar.high, low=bar.low, close=bar.close,
            volume=vol, is_closed=bar.is_closed,
        ).on_conflict_do_update(
            constraint="uq_candles_term_sym_tf_ts",
            set_={"high": bar.high, "low": bar.low, "close": bar.close,
                  "volume": vol, "is_closed": bar.is_closed},
        )
        await self.db.execute(stmt)
        await self.db.flush()
        return bar

    # ── Candle reads ────────────────────────────────────────────────────────

    async def get_candles(
        self, symbol: str, timeframe: str, *,
        start: datetime | None = None, end: datetime | None = None,
        limit: int = 500,
    ) -> list[OHLCBar]:
        stmt = select(CandleModel).where(
            CandleModel.symbol == symbol, CandleModel.timeframe == timeframe,
        )
        if start is not None:
            stmt = stmt.where(CandleModel.ts >= start)
        if end is not None:
            stmt = stmt.where(CandleModel.ts <= end)
        stmt = stmt.order_by(CandleModel.ts.desc()).limit(limit)
        rows = reversed((await self.db.execute(stmt)).scalars().all())
        return [self.candle_from_orm(r) for r in rows]

    async def get_latest_candle(self, symbol: str, timeframe: str) -> OHLCBar | None:
        stmt = select(CandleModel).where(
            CandleModel.symbol == symbol, CandleModel.timeframe == timeframe,
        ).order_by(CandleModel.ts.desc()).limit(1)
        m = (await self.db.execute(stmt)).scalar_one_or_none()
        return self.candle_from_orm(m) if m else None
