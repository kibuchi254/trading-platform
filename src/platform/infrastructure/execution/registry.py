"""Execution adapter registry — pluggable broker/exchange factory.

The platform never assumes MT5 at the application layer. Instead, every
execution venue is accessed through an :class:`ExecutionAdapter`, and
adapters are looked up by *kind* (e.g. ``"mt5"``, ``"paper"``) via the
:class:`ExecutionAdapterRegistry`.

This module ships two built-in adapter kinds:

  * ``"mt5"``   — :class:`BridgeClientAdapter`, a thin wrapper around the
                  async :class:`BridgeClient` that binds to a single
                  ``terminal_id`` and adapts its keyword-call API to the
                  ExecutionAdapter interface.
  * ``"paper"`` — :class:`PaperBrokerAdapter`, an in-memory simulator for
                  backtests, paper trading and CI.

Third-party plugins (e.g. a Binance FIX adapter) can register themselves
at import time:

.. code-block:: python

    from platform.infrastructure.execution import get_adapter_registry
    from my_plugin import BinanceAdapter

    get_adapter_registry().register("binance", BinanceAdapter)

Use :func:`get_adapter_registry` to obtain the process-wide singleton; it
is pre-populated with the two built-in adapters above.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from platform.core.logging import get_logger
from platform.infrastructure.execution.adapter_base import (
    AccountSnapshot,
    ExecutionAdapter,
    ExecutionReport,
    OrderRequest,
    PositionSnapshot,
)
from platform.infrastructure.execution.paper_broker import PaperBrokerAdapter
from platform.infrastructure.mt5_bridge.client import BridgeClient
from platform.infrastructure.mt5_bridge.protocol import BridgeMessage

_log = get_logger(__name__)


# ── BridgeClient → ExecutionAdapter wrapper ─────────────────────────────────


def _parse_dt(raw: Any) -> datetime:
    """Parse a datetime from a string, datetime, or None — fallback to now."""
    if raw is None:
        return datetime.now(timezone.utc)
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc)
    return datetime.now(timezone.utc)


def _execution_report_from_reply(
    default_client_order_id: str, reply: BridgeMessage
) -> ExecutionReport:
    """Build an :class:`ExecutionReport` from a BridgeClient reply payload.

    The MT5 terminal emits an ``ExecutionReportPayload``-shaped dict in the
    reply ``payload`` for order/cancel/close commands. We translate that to
    the platform-domain ``ExecutionReport`` model here.
    """
    p = reply.payload or {}
    return ExecutionReport(
        client_order_id=p.get("client_order_id") or default_client_order_id,
        broker_order_id=p.get("broker_order_id"),
        broker_execution_id=p.get("broker_execution_id") or reply.id,
        status=p.get("status", "accepted"),
        filled_volume=float(p.get("filled_volume", 0) or 0),
        avg_price=float(p["avg_price"]) if p.get("avg_price") is not None else None,
        rejection_reason=p.get("rejection_reason"),
        executed_at=_parse_dt(p.get("executed_at")),
    )


def _position_from_payload(rp: dict[str, Any]) -> PositionSnapshot:
    """Build a :class:`PositionSnapshot` from a sync_positions reply row."""
    return PositionSnapshot(
        broker_position_id=str(rp["broker_position_id"]),
        symbol=rp["symbol"],
        side=rp["side"],
        volume=float(rp["volume"]),
        open_price=float(rp["open_price"]),
        current_price=float(rp["current_price"]),
        stop_loss=float(rp["stop_loss"]) if rp.get("stop_loss") is not None else None,
        take_profit=float(rp["take_profit"]) if rp.get("take_profit") is not None else None,
        swap=float(rp.get("swap", 0) or 0),
        unrealized_pnl=float(rp.get("unrealized_pnl", 0) or 0),
        opened_at=_parse_dt(rp.get("opened_at")),
    )


class BridgeClientAdapter(ExecutionAdapter):
    """Adapts the async :class:`BridgeClient` to the :class:`ExecutionAdapter` interface.

    The :class:`BridgeClient` is terminal-scoped — every call takes a
    ``terminal_id`` keyword argument. This wrapper binds to a single
    ``terminal_id`` at construction time, so callers that want a uniform
    :class:`ExecutionAdapter` API can use it without sprinkling
    ``terminal_id`` throughout their code.

    Lifecycle notes
    ---------------
    The bridge is connectionless from the client side — terminals dial *into*
    the bridge service. As a result:

      * :meth:`connect` is a no-op (readiness is checked per-call by the
        terminal registry's ``require()``).
      * :meth:`disconnect` is a no-op (terminal sessions are managed by the
        :class:`TerminalRegistry`).

    Parameters
    ----------
    terminal_id:
        The external terminal identifier this adapter is bound to.
    client:
        Optional pre-constructed :class:`BridgeClient` (mainly for tests).
        If omitted, a fresh :class:`BridgeClient` is constructed.
    timeout:
        Default per-call timeout in seconds for bridge commands.
    """

    adapter_kind = "mt5"

    def __init__(
        self,
        terminal_id: str,
        *,
        client: BridgeClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.terminal_id: str = terminal_id
        self._client: BridgeClient = client if client is not None else BridgeClient()
        self._timeout: float = float(timeout)

    # ── Lifecycle ───────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """No-op — the bridge client is connectionless from this side.

        Terminal availability is verified lazily on each command via
        ``TerminalRegistry.require()`` (invoked inside ``BridgeClient``).
        """
        _log.info("bridge_adapter_ready", terminal_id=self.terminal_id)

    async def disconnect(self) -> None:
        """No-op — terminal sessions are managed by :class:`TerminalRegistry`."""
        _log.info("bridge_adapter_disconnected", terminal_id=self.terminal_id)

    # ── Order placement ─────────────────────────────────────────────────────

    async def place_order(self, req: OrderRequest) -> ExecutionReport:
        """Forward a place-order request to the bound terminal.

        Blocks until the terminal acks (or the command times out).
        """
        reply: BridgeMessage = await self._client.place_order(
            terminal_id=self.terminal_id,
            symbol=req.symbol,
            side=req.side,
            order_type=req.order_type,
            volume=req.volume,
            price=req.price,
            stop_loss=req.stop_loss,
            take_profit=req.take_profit,
            client_order_id=req.client_order_id,
            comment=req.comment,
            timeout=self._timeout,
        )
        return _execution_report_from_reply(req.client_order_id, reply)

    async def cancel_order(self, broker_order_id: str) -> ExecutionReport:
        """Forward a cancel-order request to the bound terminal."""
        reply = await self._client.cancel_order(
            terminal_id=self.terminal_id,
            broker_order_id=broker_order_id,
            timeout=self._timeout,
        )
        return _execution_report_from_reply(broker_order_id, reply)

    async def close_position(
        self, broker_position_id: str, volume: float | None = None
    ) -> ExecutionReport:
        """Forward a close-position request to the bound terminal."""
        reply = await self._client.close_position(
            terminal_id=self.terminal_id,
            broker_position_id=broker_position_id,
            volume=volume,
            timeout=self._timeout,
        )
        # The terminal may reply with either an execution-report-shaped
        # payload (if the close was implemented as an opposite market order)
        # or a position-update-shaped payload. We normalise to an
        # ExecutionReport; downstream code reconciles via the event bus.
        return _execution_report_from_reply(f"close-{broker_position_id}", reply)

    async def modify_position(
        self,
        broker_position_id: str,
        *,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> ExecutionReport:
        """Forward a modify-position request to the bound terminal.

        The :class:`BridgeClient` does not currently expose a high-level
        ``modify_position`` method, so we send the raw
        ``MODIFY_POSITION`` command via the command queue and synthesise an
        ``accepted`` :class:`ExecutionReport` from the reply.
        """
        # Local imports to avoid cycles in case this module is imported
        # very early during process startup.
        from platform.infrastructure.mt5_bridge.command_queue import get_command_queue
        from platform.infrastructure.mt5_bridge.protocol import CommandType, command
        from platform.infrastructure.mt5_bridge.registry import get_registry

        registry = get_registry()
        rec = await registry.require(self.terminal_id)
        cmd = command(
            CommandType.MODIFY_POSITION,
            terminal_id=self.terminal_id,
            payload={
                "broker_position_id": broker_position_id,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
            },
        )
        await rec.session.send(cmd)
        reply = await get_command_queue().enqueue(cmd, timeout=self._timeout)
        # POSITION_MODIFIED replies don't fit the ExecutionReport shape;
        # we return a synthetic ``accepted`` report so the caller knows the
        # modification was acknowledged.
        now = datetime.now(timezone.utc)
        return ExecutionReport(
            client_order_id=reply.payload.get("client_order_id", f"modify-{broker_position_id}"),
            broker_order_id=reply.payload.get("broker_order_id"),
            broker_execution_id=reply.id,
            status="accepted",
            filled_volume=0.0,
            executed_at=now,
        )

    # ── Sync ────────────────────────────────────────────────────────────────

    async def sync_positions(self) -> list[PositionSnapshot]:
        """Pull all open positions from the bound terminal."""
        reply = await self._client.sync_positions(
            terminal_id=self.terminal_id, timeout=30.0
        )
        rows = reply.payload.get("positions", []) if reply.payload else []
        return [_position_from_payload(rp) for rp in rows]

    async def sync_account(self) -> AccountSnapshot:
        """Pull the account snapshot from the bound terminal."""
        reply = await self._client.sync_account(
            terminal_id=self.terminal_id, timeout=self._timeout
        )
        p = reply.payload or {}
        return AccountSnapshot(
            balance=float(p.get("balance", 0) or 0),
            equity=float(p.get("equity", 0) or 0),
            margin=float(p.get("margin", 0) or 0),
            free_margin=float(p.get("free_margin", 0) or 0),
            currency=p.get("currency", "USD") or "USD",
            leverage=int(p.get("leverage", 100) or 100),
        )

    async def subscribe_ticks(self, symbols: list[str]) -> None:
        """Subscribe the bound terminal to tick updates for ``symbols``."""
        await self._client.subscribe_ticks(
            terminal_id=self.terminal_id, symbols=symbols, timeout=5.0
        )

    async def get_history(
        self,
        *,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """Not exposed via :class:`BridgeClient` — historical bars are loaded
        from the DB / market-data store. Returns an empty list."""
        return []


# ── Registry ────────────────────────────────────────────────────────────────


class ExecutionAdapterRegistry:
    """Pluggable registry of execution-adapter factories.

    Adapters are registered by *kind* (a short string such as ``"mt5"`` or
    ``"paper"``). Each registration is a factory (typically the adapter
    class itself) which is called with ``**kwargs`` to produce an adapter
    instance.

    The registry is intentionally simple — no plugin discovery, no DI
    container. Callers are expected to:

      1. Register their adapter kind once at import time (or via the
         pre-populated built-ins below).
      2. Call :meth:`create` to instantiate an adapter when needed.

    Example
    -------
    .. code-block:: python

        from platform.infrastructure.execution import get_adapter_registry

        registry = get_adapter_registry()
        adapter = registry.create("paper", starting_balance=50_000.0)
        report = await adapter.place_order(req)
    """

    def __init__(self) -> None:
        self._factories: dict[str, Callable[..., ExecutionAdapter]] = {}

    def register(self, kind: str, factory: Callable[..., ExecutionAdapter]) -> None:
        """Register an adapter factory under ``kind``.

        If ``kind`` is already registered, the new factory replaces the
        previous one and a warning is logged.
        """
        if kind in self._factories:
            _log.warning(
                "execution_adapter_replaced",
                kind=kind,
                old=self._factories[kind].__name__,
                new=factory.__name__,
            )
        self._factories[kind] = factory
        _log.info("execution_adapter_registered", kind=kind, factory=factory.__name__)

    def create(self, kind: str, **kwargs: Any) -> ExecutionAdapter:
        """Instantiate an adapter of the given ``kind``.

        Raises :class:`KeyError` if ``kind`` is not registered.
        """
        try:
            factory = self._factories[kind]
        except KeyError:
            available = ", ".join(sorted(self._factories)) or "<none>"
            raise KeyError(
                f"Unknown execution adapter kind: {kind!r}. "
                f"Registered kinds: {available}"
            ) from None
        return factory(**kwargs)

    def list_adapters(self) -> list[str]:
        """Return the list of registered adapter kinds."""
        return sorted(self._factories.keys())


# ── Singleton ───────────────────────────────────────────────────────────────


_registry: ExecutionAdapterRegistry | None = None


def get_adapter_registry() -> ExecutionAdapterRegistry:
    """Return the process-wide :class:`ExecutionAdapterRegistry` singleton.

    On first call, the registry is pre-populated with the built-in adapters:

      * ``"mt5"``   → :class:`BridgeClientAdapter`
      * ``"paper"`` → :class:`PaperBrokerAdapter`
    """
    global _registry
    if _registry is None:
        _registry = ExecutionAdapterRegistry()
        _registry.register("mt5", BridgeClientAdapter)
        _registry.register("paper", PaperBrokerAdapter)
    return _registry


__all__ = [
    "BridgeClientAdapter",
    "ExecutionAdapterRegistry",
    "get_adapter_registry",
]
