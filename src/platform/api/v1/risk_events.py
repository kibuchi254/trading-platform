"""Risk events REST router — the risk-event audit feed.

Wraps the `list_risk_events` query. Org-scoped via the authenticated user.
"""

from __future__ import annotations

from platform.application.queries.list_risk_events import (
    ListRiskEventsQuery,
    handle_list_risk_events,
)
from platform.core.dependencies import CurrentUser, get_current_user

from fastapi import APIRouter, Depends, Query

router = APIRouter(prefix="/risk-events", tags=["risk"])


@router.get("")
async def list_risk_events(
    user: CurrentUser = Depends(get_current_user),
    severity: str | None = Query(default=None),
    rule: str | None = Query(default=None),
    resolved: bool = Query(default=False),
    limit: int = Query(default=50, le=500),
) -> dict:
    result = await handle_list_risk_events(
        ListRiskEventsQuery(
            org_id=user.org_id,
            severity=severity,
            rule=rule,
            resolved=resolved,
            limit=limit,
        )
    )
    return result.model_dump(mode="json")
