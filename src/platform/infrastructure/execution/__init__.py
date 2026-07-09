"""Execution adapter package.

Exposes the :class:`ExecutionAdapter` abstraction along with built-in
adapters:

  * :class:`PaperBrokerAdapter`   — in-memory simulation for backtesting,
                                     paper trading and CI.
  * :class:`BridgeClientAdapter`  — wraps the async :class:`BridgeClient`
                                     for live MT5 trading.

Use :func:`get_adapter_registry` to obtain the process-wide singleton
registry, which comes pre-registered with both built-in adapters under
the ``"paper"`` and ``"mt5"`` kinds respectively.

Typical usage
-------------

.. code-block:: python

    from platform.infrastructure.execution import (
        OrderRequest, get_adapter_registry,
    )

    registry = get_adapter_registry()
    adapter = registry.create("paper", starting_balance=50_000.0)
    await adapter.connect()
    report = await adapter.place_order(
        OrderRequest(
            client_order_id="atlas-abc123",
            symbol="EURUSD",
            side="buy",
            order_type="market",
            volume=0.10,
        )
    )
"""

from __future__ import annotations

from platform.infrastructure.execution.adapter_base import (
    AccountSnapshot,
    ExecutionAdapter,
    ExecutionReport,
    OrderRequest,
    PositionSnapshot,
)
from platform.infrastructure.execution.paper_broker import PaperBrokerAdapter
from platform.infrastructure.execution.registry import (
    BridgeClientAdapter,
    ExecutionAdapterRegistry,
    get_adapter_registry,
)

__all__ = [
    "AccountSnapshot",
    "BridgeClientAdapter",
    # Core abstractions (from adapter_base)
    "ExecutionAdapter",
    # Registry
    "ExecutionAdapterRegistry",
    "ExecutionReport",
    "OrderRequest",
    # Built-in adapters
    "PaperBrokerAdapter",
    "PositionSnapshot",
    "get_adapter_registry",
]
