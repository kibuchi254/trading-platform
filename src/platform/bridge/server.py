"""Bridge Service — the WebSocket server MT5 terminals connect to.

Runs as a separate process from the REST API:
    python -m platform.bridge.server --port 9000

The bridge is *stateless* except for the in-memory terminal registry (which is
rebuilt from REGISTER events on reconnect). For HA, run multiple bridge nodes
behind a sticky-session load balancer — see `docs → Bridge sharding`.
"""

from __future__ import annotations

import argparse
import asyncio
import signal
from platform.bridge.handlers import dispatch
from platform.bridge.session import BridgeSession
from platform.core.config import get_settings
from platform.core.logging import configure_logging, get_logger
from platform.core.telemetry import start_metrics_server
from platform.infrastructure.mt5_bridge.command_queue import get_command_queue
from platform.infrastructure.mt5_bridge.registry import get_registry
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from websockets.asyncio.server import ServerConnection

_log = get_logger(__name__)


async def _on_connect(ws: ServerConnection) -> None:
    """Per-connection handler. One BridgeSession per terminal."""
    session = BridgeSession(ws)
    _log.info("connection_opened", session_id=session.id, peer=ws.remote_address)
    queue = get_command_queue()

    try:
        async for raw in ws:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            try:
                from platform.infrastructure.mt5_bridge.protocol import BridgeMessage

                msg = BridgeMessage.model_validate_json(raw)
            except Exception:
                _log.warning("invalid_message", session_id=session.id, raw=raw[:200])
                continue
            await dispatch(msg, session)
    except Exception as e:
        _log.info("connection_closed", session_id=session.id, error=str(e))
    finally:
        if session.terminal_id:
            await get_registry().unregister(session.terminal_id, reason="connection closed")
            await queue.fail_all(session.terminal_id, RuntimeError("terminal disconnected"))


async def main() -> None:
    parser = argparse.ArgumentParser(description="ATLAS MT5 Bridge Service")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    settings = get_settings()
    host = args.host or settings.bridge_host
    port = args.port or settings.bridge_port

    configure_logging()
    start_metrics_server()
    registry = get_registry()
    await registry.start_watcher()

    # Import websockets lazily so the rest of the package imports cleanly
    from websockets.asyncio.server import serve

    stop = asyncio.Future()

    def _signal_handler() -> None:
        _log.info("shutdown_signal_received")
        if not stop.done():
            stop.set_result(None)

    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, _signal_handler)

    async with serve(
        _on_connect, host, port, max_size=2**20, ping_interval=20, ping_timeout=10
    ) as server:
        _log.info("bridge_listening", host=host, port=port)
        await stop
        _log.info("bridge_stopping")
        await registry.stop_watcher()
        server.close()
        await server.wait_closed()
    _log.info("bridge_stopped")


if __name__ == "__main__":
    asyncio.run(main())
