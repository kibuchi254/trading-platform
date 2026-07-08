"""Risk REST router — view current limits, toggle kill switch."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from platform.core.dependencies import CurrentUser, get_current_user, require_role
from platform.risk.engine import get_risk_engine

router = APIRouter(prefix="/risk", tags=["risk"])


class KillSwitchOut(BaseModel):
    engaged: bool


@router.get("/kill-switch", response_model=KillSwitchOut)
async def get_kill_switch(user: CurrentUser = Depends(get_current_user)) -> KillSwitchOut:
    eng = get_risk_engine()
    return KillSwitchOut(engaged=eng.kill_switch._engaged)


@router.post("/kill-switch/engage", response_model=KillSwitchOut)
async def engage_kill_switch(
    user: CurrentUser = Depends(require_role("admin", "trader")),
) -> KillSwitchOut:
    eng = get_risk_engine()
    eng.kill_switch.engage(reason=f"manual by {user.user_id}")
    return KillSwitchOut(engaged=True)


@router.post("/kill-switch/release", response_model=KillSwitchOut)
async def release_kill_switch(
    user: CurrentUser = Depends(require_role("admin")),
) -> KillSwitchOut:
    eng = get_risk_engine()
    eng.kill_switch.release()
    return KillSwitchOut(engaged=False)
