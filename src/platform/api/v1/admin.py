"""Admin REST router — org management, user management, system metrics."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from platform.core.dependencies import CurrentUser, require_role

router = APIRouter(prefix="/admin", tags=["admin"])


class SystemStatus(BaseModel):
    terminals_online: int
    pending_commands: int
    risk_kill_switch: bool
    env: str


@router.get("/status", response_model=SystemStatus)
async def system_status(
    user: CurrentUser = Depends(require_role("admin")),
) -> SystemStatus:
    from platform.core.config import get_settings
    from platform.infrastructure.mt5_bridge.command_queue import get_command_queue
    from platform.infrastructure.mt5_bridge.registry import get_registry
    from platform.risk.engine import get_risk_engine

    registry = get_registry()
    terminals = await registry.list_online()
    queue = get_command_queue()
    risk = get_risk_engine()
    settings = get_settings()

    pending = sum(len(v) for v in queue._pending.values())

    return SystemStatus(
        terminals_online=len(terminals),
        pending_commands=pending,
        risk_kill_switch=risk.kill_switch._engaged,
        env=settings.env,
    )
