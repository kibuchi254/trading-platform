"""Replay engine — historical tick replay for backtesting & visualisation.

Reads ticks from the persisted ``ticks`` table and republishes them on
``atlas.ticks`` with a ``meta.replay=true`` flag. Subscribers that should
ignore replay traffic (e.g. the live TickStore) check that flag and short-
circuit; subscribers that should react (e.g. strategy backtests) treat the
ticks like any other.

Each replay runs in its own ``asyncio.Task`` and is tracked in
``self._sessions`` keyed by ``session_id`` (string form of the
``ReplaySession.session_id`` UUID). Speed control:
    - ``1.0``  = real-time (delays preserve original tick spacing)
    - ``10.0`` = 10× faster (delays divided by 10)
    - ``0.0``  = max speed (no delays — flush as fast as the DB can stream)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from platform.core.logging import get_logger
from platform.db.models import Tick
from platform.db.session import db_context
from platform.domain.market_data import ReplaySession, ReplayStatus
from platform.events.bus import get_event_bus
from platform.events.topics import Topic
from typing import Any
from uuid import UUID

from sqlalchemy import select

_log = get_logger(__name__)

# ── Tunables ─────────────────────────────────────────────────────────────────
BATCH_SIZE: int = 10_000  # rows read per DB round-trip
MAX_SPEED_SENTINEL: float = 1e6  # internal value for "0.0 = max speed"
POLL_INTERVAL_SEC: float = 0.05  # pause/resuse responsiveness


class _SessionState:
    """Engine-side runtime state for a single replay session.

    Wraps the domain ``ReplaySession`` aggregate with the asyncio primitives
    needed to drive a live replay task: a pause ``Event`` and the
    ``asyncio.Task`` itself.
    """

    def __init__(self, session: ReplaySession, raw_speed: float) -> None:
        self.session: ReplaySession = session
        # raw_speed=0.0 means "max speed" — store separately so we can detect
        # it in the replay loop without re-deriving from the domain aggregate.
        self.raw_speed: float = raw_speed
        self.pause_event: asyncio.Event = asyncio.Event()
        self.pause_event.set()  # not paused
        self.task: asyncio.Task[None] | None = None
        self._cursor_ts: datetime | None = None  # for seek()


class ReplayEngine:
    """Drives historical tick replays as managed asyncio tasks."""

    def __init__(self) -> None:
        self._sessions: dict[str, _SessionState] = {}

    # ── Public API ──────────────────────────────────────────────────────────

    async def start_replay(
        self,
        session_id: str | UUID,
        symbol: str,
        start: datetime,
        end: datetime,
        speed: float = 1.0,
    ) -> ReplaySession:
        """Begin replaying ticks for ``symbol`` over ``[start, end]``.

        Args:
            session_id: Unique identifier (string or UUID). Reusing an id
                that is already running is an error.
            symbol:    The ticker to replay (e.g. ``"EURUSD"``).
            start:     Replay window lower bound (inclusive).
            end:       Replay window upper bound (inclusive).
            speed:     Playback multiplier. ``1.0`` = real-time, ``10.0`` =
                       10× faster, ``0.0`` = maximum speed (no inter-tick delay).

        Returns:
            The freshly constructed ``ReplaySession`` domain aggregate.
        """
        sid = str(session_id)
        if sid in self._sessions:
            raise ValueError(f"replay session already exists: {sid}")
        if end < start:
            raise ValueError("end must be >= start")

        # The domain aggregate enforces speed_multiplier > 0; remap 0.0 to a
        # huge sentinel so the aggregate stays valid while we still know to
        # skip delays in the replay loop.
        domain_speed = speed if speed > 0 else MAX_SPEED_SENTINEL
        session = ReplaySession(
            session_id=UUID(sid) if isinstance(sid, str) else sid,
            symbol=symbol,
            start=start,
            end=end,
            speed_multiplier=domain_speed,
            status=ReplayStatus.PENDING,
        )
        session.start_session()  # PENDING → RUNNING

        state = _SessionState(session=session, raw_speed=speed)
        state.task = asyncio.create_task(self._run(state), name=f"replay:{sid}")
        self._sessions[sid] = state
        _log.info(
            "replay_started",
            session_id=sid,
            symbol=symbol,
            start=start.isoformat(),
            end=end.isoformat(),
            speed=speed,
        )
        return session

    async def pause_replay(self, session_id: str | UUID) -> None:
        """Pause a running replay. No-op if not running."""
        state = self._get_state_or_raise(session_id)
        if state.session.status == ReplayStatus.RUNNING:
            state.session.pause()
            state.pause_event.clear()
            _log.info("replay_paused", session_id=str(session_id))

    async def resume_replay(self, session_id: str | UUID) -> None:
        """Resume a paused replay. No-op if not paused."""
        state = self._get_state_or_raise(session_id)
        if state.session.status == ReplayStatus.PAUSED:
            state.session.resume()
            state.pause_event.set()
            _log.info("replay_resumed", session_id=str(session_id))

    async def stop_replay(self, session_id: str | UUID) -> None:
        """Stop a replay outright. Cancels the task and marks COMPLETED."""
        sid = str(session_id)
        state = self._sessions.pop(sid, None)
        if state is None:
            _log.warning("replay_stop_unknown_session", session_id=sid)
            return
        if state.task is not None and not state.task.done():
            state.task.cancel()
            try:
                await state.task
            except asyncio.CancelledError:
                pass
        try:
            state.session.complete()
        except Exception:
            pass
        _log.info("replay_stopped", session_id=sid)

    async def seek(self, session_id: str | UUID, timestamp: datetime) -> None:
        """Jump the replay cursor to ``timestamp``.

        Internally: stop the current task, set the cursor, and restart the
        replay from ``timestamp`` to the original ``end``. The session id is
        preserved so subscribers don't need to resubscribe.
        """
        state = self._get_state_or_raise(session_id)
        if timestamp > state.session.end or timestamp < state.session.start:
            raise ValueError("timestamp out of replay window")

        # Cancel current task cleanly.
        was_paused = state.session.status == ReplayStatus.PAUSED
        if state.task is not None and not state.task.done():
            state.task.cancel()
            try:
                await state.task
            except asyncio.CancelledError:
                pass

        state._cursor_ts = timestamp
        # Restart from the seek point — keep original end & speed.
        state.session.status = ReplayStatus.RUNNING
        state.pause_event.set()
        state.task = asyncio.create_task(self._run(state), name=f"replay:{session_id!s}")
        if was_paused:
            await self.pause_replay(session_id)
        _log.info(
            "replay_seek",
            session_id=str(session_id),
            timestamp=timestamp.isoformat(),
        )

    def list_sessions(self) -> list[ReplaySession]:
        """Return a snapshot of all tracked sessions (running, paused, completed)."""
        return [s.session for s in self._sessions.values()]

    def get_session(self, session_id: str | UUID) -> ReplaySession | None:
        """Return the domain aggregate for a session id, or ``None``."""
        state = self._sessions.get(str(session_id))
        return state.session if state else None

    # ── Internals ───────────────────────────────────────────────────────────

    def _get_state_or_raise(self, session_id: str | UUID) -> _SessionState:
        sid = str(session_id)
        state = self._sessions.get(sid)
        if state is None:
            raise KeyError(f"unknown replay session: {sid}")
        return state

    async def _run(self, state: _SessionState) -> None:
        """Replay loop — streams ticks from DB to the bus with speed control."""
        sid = str(state.session.session_id)
        try:
            cursor = state._cursor_ts or state.session.start
            end = state.session.end
            prev_ts: datetime | None = None
            total_published = 0

            while cursor <= end:
                # Respect pause.
                await state.pause_event.wait()

                # Stop early if the task was cancelled / session completed.
                if state.session.status == ReplayStatus.COMPLETED:
                    break

                batch = await self._fetch_batch(
                    symbol=state.session.symbol,
                    start=cursor,
                    end=end,
                    limit=BATCH_SIZE,
                )
                if not batch:
                    break

                for tick in batch:
                    await state.pause_event.wait()
                    await self._publish_tick(state, tick)

                    # Real-time pacing: sleep proportional to original spacing.
                    if prev_ts is not None and state.raw_speed > 0:
                        delta = (tick["ts"] - prev_ts).total_seconds()
                        delay = delta / state.raw_speed
                        if delay > 0:
                            await asyncio.sleep(delay)
                    prev_ts = tick["ts"]
                    state.session.advance(1)
                    total_published += 1

                # Advance cursor past the last tick we just emitted.
                cursor = batch[-1]["ts"]
                if len(batch) < BATCH_SIZE:
                    break  # no more rows in window

            state.session.complete()
            _log.info(
                "replay_completed",
                session_id=sid,
                ticks_published=total_published,
            )
        except asyncio.CancelledError:
            _log.info("replay_cancelled", session_id=sid)
            raise
        except Exception:
            _log.exception("replay_failed", session_id=sid)
            try:
                state.session.complete()
            except Exception:
                pass

    @staticmethod
    async def _fetch_batch(
        *,
        symbol: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Read up to ``limit`` ticks for ``symbol`` in ``[start, end]`` ascending."""
        stmt = (
            select(
                Tick.terminal_id,
                Tick.symbol,
                Tick.bid,
                Tick.ask,
                Tick.last,
                Tick.volume,
                Tick.ts,
            )
            .where(
                Tick.symbol == symbol,
                Tick.ts >= start,
                Tick.ts <= end,
            )
            .order_by(Tick.ts.asc())
            .limit(limit)
        )
        async with db_context() as db:
            rows = (await db.execute(stmt)).all()
        return [
            {
                "terminal_id": r.terminal_id,
                "symbol": r.symbol,
                "bid": float(r.bid),
                "ask": float(r.ask),
                "last": float(r.last) if r.last is not None else None,
                "volume": float(r.volume) if r.volume is not None else None,
                "ts": r.ts if r.ts.tzinfo else r.ts.replace(tzinfo=UTC),
            }
            for r in rows
        ]

    @staticmethod
    async def _publish_tick(state: _SessionState, tick: dict[str, Any]) -> None:
        """Republish a historical tick on ``atlas.ticks`` with ``meta.replay=true``."""
        bus = get_event_bus()
        payload: dict[str, Any] = {
            "terminal_id": str(tick["terminal_id"]) if tick["terminal_id"] else None,
            "symbol": tick["symbol"],
            "bid": tick["bid"],
            "ask": tick["ask"],
            "last": tick["last"],
            "volume": tick["volume"],
            "ts": tick["ts"].isoformat(),
            "meta": {
                "replay": True,
                "session_id": str(state.session.session_id),
            },
        }
        await bus.publish(Topic.TICKS, payload)

    # ── Shutdown ────────────────────────────────────────────────────────────

    async def stop_all(self) -> None:
        """Cancel every active replay. Call on application shutdown."""
        sids = list(self._sessions.keys())
        for sid in sids:
            await self.stop_replay(sid)


# ── Singleton ────────────────────────────────────────────────────────────────
_engine: ReplayEngine | None = None


def get_replay_engine() -> ReplayEngine:
    """Return the process-wide ``ReplayEngine`` singleton."""
    global _engine
    if _engine is None:
        _engine = ReplayEngine()
    return _engine
