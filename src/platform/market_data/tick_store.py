"""Tick store — high-throughput tick persistence.

Subscribes to ``atlas.ticks`` and buffers incoming ticks in an
``asyncio.Queue``. A background flusher task batches writes — either every
1000 ticks or every 5 seconds, whichever comes first — and persists them via
SQLAlchemy Core ``insert().values([...])`` (the fastest non-COPY path through
asyncpg, short of a true binary ``COPY``).

Backpressure: if the buffer exceeds ``MAX_BUFFERED`` (100_000) ticks, the
oldest entries are dropped and a warning is logged. This protects the live
trading path — a missed tick is far cheaper than a stalled event loop.

Typical use::

    store = get_tick_store()
    await store.start()
    ...
    await store.stop()        # flushes remaining buffer + cancels flusher
"""
from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import insert

from platform.core.logging import get_logger
from platform.db.models import Tick
from platform.db.session import get_engine
from platform.events.bus import get_event_bus
from platform.events.topics import Topic

_log = get_logger(__name__)

# ── Tunables ─────────────────────────────────────────────────────────────────
BATCH_SIZE: int = 1_000          # max ticks per flush
FLUSH_INTERVAL_SEC: float = 5.0  # max seconds between flushes
MAX_BUFFERED: int = 100_000      # backpressure threshold


class TickStore:
    """High-throughput tick persistence.

    Lifecycle:
        - ``start()`` subscribes to ``atlas.ticks`` and spawns the flusher task.
        - ``stop()`` cancels the flusher and drains any remaining buffer.
        - ``flush_now()`` triggers an immediate flush (useful for tests / shutdown).

    The buffer is a ``deque`` protected by an ``asyncio.Lock`` — chosen over
    ``asyncio.Queue`` because we need O(1) popleft for backpressure drops and
    bulk-drain for batch flushing, neither of which ``Queue`` exposes cleanly.
    """

    def __init__(self) -> None:
        self._buffer: deque[dict[str, Any]] = deque()
        self._lock: asyncio.Lock = asyncio.Lock()
        self._flusher: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event = asyncio.Event()
        self._flush_event: asyncio.Event = asyncio.Event()

        # ── Stats ───────────────────────────────────────────────────────────
        self._total_written: int = 0
        self._total_dropped: int = 0
        self._total_flushes: int = 0
        self._last_flush_at: datetime | None = None
        self._started_at: datetime | None = None

    # ── Lifecycle ───────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Subscribe to ``atlas.ticks`` and start the background flusher."""
        if self._flusher is not None:
            _log.warning("tick_store_already_started")
            return
        bus = get_event_bus()
        bus.subscribe(Topic.TICKS, self._on_tick)
        self._stop_event.clear()
        self._started_at = datetime.now(timezone.utc)
        self._flusher = asyncio.create_task(self._flush_loop(), name="tick_store_flusher")
        _log.info(
            "tick_store_started",
            batch_size=BATCH_SIZE,
            flush_interval=FLUSH_INTERVAL_SEC,
            max_buffered=MAX_BUFFERED,
        )

    async def stop(self) -> None:
        """Cancel the flusher and flush any remaining ticks.

        Safe to call multiple times. Blocks until the final flush completes
        (or fails) so callers can shut down their DB engine immediately after.
        """
        if self._flusher is None:
            return
        self._stop_event.set()
        self._flush_event.set()
        try:
            await asyncio.wait_for(self._flusher, timeout=30.0)
        except asyncio.TimeoutError:
            _log.warning("tick_store_flusher_timeout_on_stop")
            self._flusher.cancel()
        except asyncio.CancelledError:
            pass
        # Best-effort final drain in case the loop exited between checks.
        await self.flush_now()
        self._flusher = None
        _log.info(
            "tick_store_stopped",
            total_written=self._total_written,
            total_dropped=self._total_dropped,
        )

    # ── Event subscription ──────────────────────────────────────────────────

    async def _on_tick(self, payload: dict[str, Any]) -> None:
        """Event-bus handler — append to buffer with backpressure."""
        record = self._coerce_tick(payload)
        if record is None:
            return

        async with self._lock:
            self._buffer.append(record)
            overflow = len(self._buffer) - MAX_BUFFERED
            if overflow > 0:
                # Drop oldest — they are the most stale by definition.
                for _ in range(overflow):
                    self._buffer.popleft()
                self._total_dropped += overflow
                _log.warning(
                    "tick_store_backpressure_dropped",
                    dropped=overflow,
                    buffered=len(self._buffer),
                )

        # Wake the flusher early if we've crossed the batch threshold.
        if len(self._buffer) >= BATCH_SIZE:
            self._flush_event.set()

    @staticmethod
    def _coerce_tick(payload: dict[str, Any]) -> dict[str, Any] | None:
        """Convert a bus payload into a row dict suitable for ``Tick`` insert.

        Returns ``None`` if required fields are missing — the bad tick is
        logged and skipped rather than crashing the subscriber.
        """
        try:
            terminal_id_raw = payload["terminal_id"]
            # Accept UUID or string; SQLAlchemy will bind either.
            if isinstance(terminal_id_raw, str):
                terminal_id: UUID = UUID(terminal_id_raw)
            else:
                terminal_id = terminal_id_raw
            ts_raw = payload["ts"]
            ts = datetime.fromisoformat(ts_raw) if isinstance(ts_raw, str) else ts_raw
            return {
                "terminal_id": terminal_id,
                "symbol": str(payload["symbol"]),
                "bid": float(payload["bid"]),
                "ask": float(payload["ask"]),
                "last": float(payload["last"]) if payload.get("last") is not None else None,
                "volume": float(payload["volume"]) if payload.get("volume") is not None else None,
                "ts": ts,
            }
        except (KeyError, ValueError, TypeError):
            _log.exception("tick_store_bad_payload", payload=payload)
            return None

    # ── Flusher ─────────────────────────────────────────────────────────────

    async def _flush_loop(self) -> None:
        """Background loop — flushes every ``FLUSH_INTERVAL_SEC`` or on signal."""
        while not self._stop_event.is_set():
            self._flush_event.clear()
            try:
                await asyncio.wait_for(
                    self._flush_event.wait(), timeout=FLUSH_INTERVAL_SEC
                )
            except asyncio.TimeoutError:
                pass  # periodic flush
            try:
                await self._flush_batch()
            except Exception:  # noqa: BLE001
                _log.exception("tick_store_flush_failed")
                # Back off briefly to avoid a tight error loop hammering Postgres.
                await asyncio.sleep(1.0)

        # Final drain on shutdown.
        try:
            await self._flush_batch()
        except Exception:  # noqa: BLE001
            _log.exception("tick_store_final_flush_failed")

    async def flush_now(self) -> int:
        """Flush the entire buffer immediately. Returns rows written."""
        return await self._flush_batch()

    async def _flush_batch(self) -> int:
        """Drain the buffer and bulk-insert up to ``BATCH_SIZE`` rows.

        Larger buffers are drained in successive ``BATCH_SIZE`` chunks within
        a single call so that ``flush_now()`` fully empties the queue while
        still keeping individual INSERTs at the optimal batch size.
        """
        total = 0
        while True:
            async with self._lock:
                if not self._buffer:
                    break
                chunk = [self._buffer.popleft() for _ in range(min(BATCH_SIZE, len(self._buffer)))]
            if not chunk:
                break
            written = await self._bulk_insert(chunk)
            total += written
            self._total_written += written
            self._total_flushes += 1
            self._last_flush_at = datetime.now(timezone.utc)
            _log.debug(
                "tick_store_flush",
                rows=written,
                buffered=len(self._buffer),
            )
        return total

    @staticmethod
    async def _bulk_insert(rows: list[dict[str, Any]]) -> int:
        """Bulk-insert a batch of tick rows via SQLAlchemy Core.

        Uses ``insert(Tick.__table__).values([...])`` which compiles to a
        single multi-row ``INSERT ... VALUES (...), (...), ...`` statement —
        the fastest path through asyncpg short of a binary ``COPY``. On
        conflict we silently skip (rare duplicate-tick replays should not
        crash the flusher).
        """
        if not rows:
            return 0
        engine = get_engine()
        stmt = (
            insert(Tick.__table__)
            .values(rows)
            .on_conflict_do_nothing()  # type: ignore[attr-defined]
        )
        async with engine.begin() as conn:
            result = await conn.execute(stmt)
            return result.rowcount or len(rows)

    # ── Observability ───────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Return a snapshot of buffer and write-throughput stats.

        Keys:
            - ``buffered_count`` — ticks currently waiting in the buffer.
            - ``total_written`` — ticks successfully persisted since ``start()``.
            - ``total_dropped`` — ticks dropped due to backpressure.
            - ``total_flushes`` — number of INSERT batches executed.
            - ``write_rate`` — rolling avg rows/sec since ``started_at``.
            - ``last_flush_at`` — ISO timestamp of the most recent flush.
        """
        now = datetime.now(timezone.utc)
        elapsed = (
            (now - self._started_at).total_seconds()
            if self._started_at is not None else 0.0
        )
        write_rate = self._total_written / elapsed if elapsed > 0 else 0.0
        return {
            "buffered_count": len(self._buffer),
            "total_written": self._total_written,
            "total_dropped": self._total_dropped,
            "total_flushes": self._total_flushes,
            "write_rate": round(write_rate, 2),
            "last_flush_at": self._last_flush_at.isoformat() if self._last_flush_at else None,
            "started_at": self._started_at.isoformat() if self._started_at else None,
        }


# ── Singleton ────────────────────────────────────────────────────────────────
_store: TickStore | None = None


def get_tick_store() -> TickStore:
    """Return the process-wide ``TickStore`` singleton."""
    global _store
    if _store is None:
        _store = TickStore()
    return _store
