"""In-memory terminal registry — tracks every connected MT5 terminal.

A new instance is created per Bridge Service process. For multi-replica
deployments, the registry is sharded by `terminal_id` hash and a Redis
backed map of `terminal_id → bridge_node_id` is consulted for routing
(see docs → Scaling Strategy → Bridge sharding).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from platform.core.exceptions import TerminalOffline
from platform.core.logging import get_logger
from platform.core.telemetry import TERMINALS_ONLINE
from platform.infrastructure.mt5_bridge.protocol import BridgeMessage, CommandType

if TYPE_CHECKING:
    from platform.bridge.session import BridgeSession

_log = get_logger(__name__)


@dataclass
class TerminalRecord:
    """Live snapshot of a connected terminal."""
    terminal_id: str
    broker: str
    account: str
    version: str | None
    symbols: list[str]
    capabilities: dict
    session: "BridgeSession"
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_heartbeat_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "online"  # online | degraded | offline

    def is_alive(self, timeout_seconds: int) -> bool:
        return (datetime.now(timezone.utc) - self.last_heartbeat_at) < timedelta(seconds=timeout_seconds)


class TerminalRegistry:
    """Async-safe registry of connected terminals."""

    def __init__(self, heartbeat_timeout_seconds: int = 30) -> None:
        self._terminals: dict[str, TerminalRecord] = {}
        self._lock = asyncio.Lock()
        self._heartbeat_timeout = heartbeat_timeout_seconds
        self._watcher_task: asyncio.Task | None = None

    async def register(self, record: TerminalRecord) -> None:
        async with self._lock:
            existing = self._terminals.get(record.terminal_id)
            if existing is not None:
                _log.warning(
                    "terminal_replaced", terminal_id=record.terminal_id,
                    old_session=existing.session.id, new_session=record.session.id,
                )
                # Politely disconnect the previous session to avoid ghost connections
                await existing.session.close(code=4001, reason="Replaced by new connection")
            self._terminals[record.terminal_id] = record
        TERMINALS_ONLINE.inc()
        _log.info("terminal_registered", terminal_id=record.terminal_id, broker=record.broker)

    async def unregister(self, terminal_id: str, *, reason: str = "disconnected") -> None:
        async with self._lock:
            rec = self._terminals.pop(terminal_id, None)
        if rec is None:
            return
        TERMINALS_ONLINE.dec()
        _log.info("terminal_unregistered", terminal_id=terminal_id, reason=reason)

    async def heartbeat(self, terminal_id: str) -> None:
        async with self._lock:
            rec = self._terminals.get(terminal_id)
            if rec is None:
                return
            rec.last_heartbeat_at = datetime.now(timezone.utc)
            if rec.status != "online":
                rec.status = "online"
                _log.info("terminal_recovered", terminal_id=terminal_id)

    async def get(self, terminal_id: str) -> TerminalRecord | None:
        async with self._lock:
            return self._terminals.get(terminal_id)

    async def require(self, terminal_id: str) -> TerminalRecord:
        rec = await self.get(terminal_id)
        if rec is None or not rec.is_alive(self._heartbeat_timeout):
            raise TerminalOffline(f"Terminal {terminal_id} not online")
        return rec

    async def list_online(self) -> list[TerminalRecord]:
        async with self._lock:
            return list(self._terminals.values())

    async def select_for_symbol(self, symbol: str, *, preferred_broker: str | None = None) -> TerminalRecord | None:
        """Pick a terminal that has the symbol. Crude first-pass; can be extended
        with load-aware routing, latency-aware routing, etc."""
        async with self._lock:
            candidates = [t for t in self._terminals.values() if symbol in t.symbols and t.is_alive(self._heartbeat_timeout)]
        if not candidates:
            return None
        if preferred_broker:
            for c in candidates:
                if c.broker == preferred_broker:
                    return c
        return candidates[0]

    # ── Heartbeat watcher ──────────────────────────────────────────────────

    async def start_watcher(self) -> None:
        if self._watcher_task is None or self._watcher_task.done():
            self._watcher_task = asyncio.create_task(self._watch_loop(), name="bridge-heartbeat-watcher")

    async def stop_watcher(self) -> None:
        if self._watcher_task is not None:
            self._watcher_task.cancel()
            try:
                await self._watcher_task
            except asyncio.CancelledError:
                pass
            self._watcher_task = None

    async def _watch_loop(self) -> None:
        """Mark terminals degraded/offline if heartbeat stops."""
        while True:
            try:
                await asyncio.sleep(5)
                now = datetime.now(timezone.utc)
                async with self._lock:
                    for tid, rec in list(self._terminals.items()):
                        elapsed = (now - rec.last_heartbeat_at).total_seconds()
                        if elapsed > self._heartbeat_timeout * 2:
                            _log.warning("terminal_offline_no_heartbeat", terminal_id=tid, elapsed_s=elapsed)
                            # Mark offline but keep entry so caller gets a clean error
                            rec.status = "offline"
                            # Schedule eviction (don't await inside lock)
                            asyncio.create_task(self._evict(tid, rec, reason="heartbeat_timeout"))
                        elif elapsed > self._heartbeat_timeout:
                            rec.status = "degraded"
                            _log.info("terminal_degraded", terminal_id=tid, elapsed_s=elapsed)
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001
                _log.exception("heartbeat_watcher_error")

    async def _evict(self, terminal_id: str, rec: TerminalRecord, *, reason: str) -> None:
        try:
            await rec.session.close(code=4002, reason=reason)
        finally:
            await self.unregister(terminal_id, reason=reason)


# Singleton per process
_registry: TerminalRegistry | None = None


def get_registry() -> TerminalRegistry:
    global _registry
    if _registry is None:
        from platform.core.config import get_settings
        settings = get_settings()
        _registry = TerminalRegistry(heartbeat_timeout_seconds=settings.bridge_heartbeat_timeout_seconds)
    return _registry
