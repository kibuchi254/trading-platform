"""Per-terminal command queue — tracks pending commands awaiting acknowledgements.

Each command sent to a terminal gets a future. When the matching execution
report (or ack) arrives, the future is resolved. If the terminal goes offline
or the command times out, the future is rejected.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from platform.core.exceptions import CommandTimeout
from platform.core.logging import get_logger
from platform.core.telemetry import BRIDGE_COMMANDS, BRIDGE_COMMAND_LATENCY
from platform.infrastructure.mt5_bridge.protocol import BridgeMessage, CommandType

_log = get_logger(__name__)


@dataclass
class PendingCommand:
    command: BridgeMessage
    future: asyncio.Future[BridgeMessage]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    timeout_seconds: float = 10.0


class CommandQueue:
    """Tracks pending commands per terminal.

    A single queue per process; commands are routed to terminals via the
    BridgeSession. For multi-process scaling, use a Redis Stream per terminal
    and have any bridge node consume — see `docs → Bridge sharding`.
    """

    def __init__(self) -> None:
        # terminal_id -> {command_id: PendingCommand}
        self._pending: dict[str, dict[str, PendingCommand]] = {}
        self._lock = asyncio.Lock()
        self._timeout_task: asyncio.Task | None = None

    async def enqueue(self, command: BridgeMessage, *, timeout: float = 10.0) -> BridgeMessage:
        """Send a command and await the matching reply.

        Raises `CommandTimeout` if no reply within `timeout` seconds.
        """
        terminal_id = command.terminal_id or ""
        if not terminal_id:
            raise ValueError("Command must have terminal_id")

        loop = asyncio.get_running_loop()
        future: asyncio.Future[BridgeMessage] = loop.create_future()
        pending = PendingCommand(command=command, future=future, timeout_seconds=timeout)

        async with self._lock:
            self._pending.setdefault(terminal_id, {})[command.id] = pending

        # Timeout watchdog
        async def _timeout() -> None:
            try:
                await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError:
                await self._fail(terminal_id, command.id, CommandTimeout(
                    f"Command {command.t} timed out after {timeout}s",
                ))
            except Exception:
                pass  # future resolved normally

        asyncio.create_task(_timeout(), name=f"cmd-timeout-{command.id}")
        return await future

    async def resolve(self, terminal_id: str, command_id: str, reply: BridgeMessage) -> None:
        """Resolve a pending command with the given reply."""
        async with self._lock:
            bucket = self._pending.get(terminal_id, {})
            pending = bucket.pop(command_id, None)
        if pending is None:
            _log.warning("reply_for_unknown_command", terminal_id=terminal_id, command_id=command_id)
            return
        elapsed = (datetime.now(timezone.utc) - pending.created_at).total_seconds()
        BRIDGE_COMMAND_LATENCY.labels(command=pending.command.t).observe(elapsed)
        BRIDGE_COMMANDS.labels(command=pending.command.t, terminal_id=terminal_id, result="ok").inc()
        if not pending.future.done():
            pending.future.set_result(reply)

    async def fail_all(self, terminal_id: str, exc: Exception) -> None:
        """Fail every pending command for a terminal (used on disconnect)."""
        async with self._lock:
            bucket = self._pending.pop(terminal_id, {})
        for cmd_id, pending in bucket.items():
            BRIDGE_COMMANDS.labels(command=pending.command.t, terminal_id=terminal_id, result="error").inc()
            if not pending.future.done():
                pending.future.set_exception(exc)
            _log.warning("command_failed", terminal_id=terminal_id, command_id=cmd_id, error=str(exc))

    async def _fail(self, terminal_id: str, command_id: str, exc: Exception) -> None:
        async with self._lock:
            bucket = self._pending.get(terminal_id, {})
            pending = bucket.pop(command_id, None)
        if pending is None:
            return
        BRIDGE_COMMANDS.labels(command=pending.command.t, terminal_id=terminal_id, result="timeout").inc()
        if not pending.future.done():
            pending.future.set_exception(exc)


_queue: CommandQueue | None = None


def get_command_queue() -> CommandQueue:
    global _queue
    if _queue is None:
        _queue = CommandQueue()
    return _queue
