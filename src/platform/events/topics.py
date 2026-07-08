"""Topic registry for the event bus. Centralizing here avoids typos."""
from __future__ import annotations


class Topic:
    TICKS = "atlas.ticks"
    EXECUTION_REPORTS = "atlas.execution_reports"
    POSITION_UPDATES = "atlas.position_updates"
    ACCOUNT_UPDATES = "atlas.account_updates"
    SIGNALS = "atlas.signals"
    ORDERS = "atlas.orders"
    RISK_EVENTS = "atlas.risk_events"
    AI_RESULTS = "atlas.ai_results"
    TERMINAL_EVENTS = "atlas.terminal_events"
    NOTIFICATIONS = "atlas.notifications"
    AUDIT = "atlas.audit"
