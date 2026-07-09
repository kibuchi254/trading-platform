"""Engage the kill switch — block all trading for the org immediately.

Vertical slice:

  API → command → risk.kill_switch.engage(reason)
        → publish RISK_EVENTS (severity=kill, action=kill)
        → fire a CRITICAL notification via the dispatcher
        → return

The kill switch is process-wide state held on the :class:`RiskEngine`
singleton; once engaged, every subsequent :meth:`RiskEngine.check_order`
raises :class:`RiskLimitBreached` and the order never reaches the bridge.
"""

from __future__ import annotations

from datetime import UTC, datetime
from platform.core.logging import get_logger
from platform.events.bus import get_event_bus
from platform.events.topics import Topic
from platform.risk.engine import get_risk_engine
from uuid import UUID

from pydantic import BaseModel

_log = get_logger(__name__)


# ── Command + DTO ──────────────────────────────────────────────────────────


class EngageKillSwitchCommand(BaseModel):
    org_id: UUID
    user_id: UUID
    reason: str = "manual"


class EngageKillSwitchResult(BaseModel):
    engaged: bool
    reason: str
    engaged_at: str
    notification_dispatched: bool


# ── Handler ─────────────────────────────────────────────────────────────────


async def handle_engage_kill_switch(cmd: EngageKillSwitchCommand) -> EngageKillSwitchResult:
    """Flip the kill switch on, scream on the event bus, and notify operators."""
    risk = get_risk_engine()
    risk.kill_switch.engage(reason=cmd.reason)

    now = datetime.now(UTC)
    payload = {
        "type": "kill_switch_engaged",
        "org_id": str(cmd.org_id),
        "rule": "kill_switch",
        "severity": "kill",
        "action": "kill",
        "details": {
            "reason": cmd.reason,
            "engaged_by": str(cmd.user_id),
            "engaged_at": now.isoformat(),
        },
    }
    bus = get_event_bus()
    await bus.publish(Topic.RISK_EVENTS, payload)

    # Fan out a CRITICAL notification to every configured channel. We import
    # lazily so this command remains importable even before the dispatcher
    # subsystem is fully wired (e.g. in unit tests).
    notification_dispatched = False
    try:
        from platform.notifications.base import get_dispatcher

        dispatcher = get_dispatcher()
        results = await dispatcher.dispatch_to_all(
            subject=f"[ATLAS] Kill switch engaged — {cmd.reason}",
            body=(
                f"Kill switch engaged at {now.isoformat()}.\n"
                f"Org: {cmd.org_id}\n"
                f"Reason: {cmd.reason}\n"
                f"Engaged by: {cmd.user_id}\n\n"
                "All order placement is now blocked until the kill switch "
                "is explicitly released."
            ),
            priority="CRITICAL",
            meta={
                "org_id": str(cmd.org_id),
                "user_id": str(cmd.user_id),
                "category": "risk.kill_switch",
            },
        )
        notification_dispatched = any(results.values()) if results else False
    except Exception:
        _log.exception("kill_switch_notification_failed", org_id=str(cmd.org_id))

    _log.critical(
        "kill_switch_engaged",
        org_id=str(cmd.org_id),
        reason=cmd.reason,
        engaged_by=str(cmd.user_id),
        notification_dispatched=notification_dispatched,
    )
    return EngageKillSwitchResult(
        engaged=True,
        reason=cmd.reason,
        engaged_at=now.isoformat(),
        notification_dispatched=notification_dispatched,
    )
