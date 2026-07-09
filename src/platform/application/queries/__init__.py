"""Application queries — CQRS read side.

Each query is a Pydantic model + handler pair. Queries never mutate state;
they read directly from the ORM via ``db_context()`` and return DTOs.

Some queries layer in live runtime state from the bridge registry
(:mod:`platform.infrastructure.mt5_bridge.registry`) or run the AI
orchestrator (:mod:`platform.ai.orchestrator`) — these are clearly the
exception, not the rule.
"""

from __future__ import annotations

from platform.application.queries.get_ai_analysis import (
    GetAIAnalysisQuery,
    GetAIAnalysisResult,
    ModulePrediction,
    handle_get_ai_analysis,
)
from platform.application.queries.get_performance import (
    GetPerformanceQuery,
    GetPerformanceResult,
    PerformanceSummary,
    handle_get_performance,
)
from platform.application.queries.get_terminal_detail import (
    AccountDetail,
    GetTerminalDetailQuery,
    TerminalDetail,
    handle_get_terminal_detail,
)
from platform.application.queries.list_orders import (
    ListOrdersQuery,
    ListOrdersResult,
    OrderSummary,
    handle_list_orders,
)
from platform.application.queries.list_positions import (
    ListPositionsQuery,
    ListPositionsResult,
    PositionSummary,
    handle_list_positions,
)
from platform.application.queries.list_risk_events import (
    ListRiskEventsQuery,
    ListRiskEventsResult,
    RiskEventSummary,
    handle_list_risk_events,
)
from platform.application.queries.list_signals import (
    ListSignalsQuery,
    ListSignalsResult,
    SignalSummary,
    handle_list_signals,
)
from platform.application.queries.list_strategies import (
    ListStrategiesQuery,
    ListStrategiesResult,
    StrategySummary,
    handle_list_strategies,
)
from platform.application.queries.list_terminals import (
    ListTerminalsQuery,
    ListTerminalsResult,
    TerminalSummary,
    handle_list_terminals,
)
from platform.application.queries.list_trades import (
    ListTradesQuery,
    ListTradesResult,
    TradeSummary,
    handle_list_trades,
)

__all__ = [
    "AccountDetail",
    "GetAIAnalysisQuery",
    "GetAIAnalysisResult",
    # Analytics
    "GetPerformanceQuery",
    "GetPerformanceResult",
    "GetTerminalDetailQuery",
    # Trading reads
    "ListOrdersQuery",
    "ListOrdersResult",
    "ListPositionsQuery",
    "ListPositionsResult",
    "ListRiskEventsQuery",
    "ListRiskEventsResult",
    "ListSignalsQuery",
    "ListSignalsResult",
    # Strategies / signals / risk
    "ListStrategiesQuery",
    "ListStrategiesResult",
    # Terminals
    "ListTerminalsQuery",
    "ListTerminalsResult",
    "ListTradesQuery",
    "ListTradesResult",
    "ModulePrediction",
    "OrderSummary",
    "PerformanceSummary",
    "PositionSummary",
    "RiskEventSummary",
    "SignalSummary",
    "StrategySummary",
    "TerminalDetail",
    "TerminalSummary",
    "TradeSummary",
    "handle_get_ai_analysis",
    "handle_get_performance",
    "handle_get_terminal_detail",
    "handle_list_orders",
    "handle_list_positions",
    "handle_list_risk_events",
    "handle_list_signals",
    "handle_list_strategies",
    "handle_list_terminals",
    "handle_list_trades",
]
