"""Audit log REST router (admin) — immutable audit trail.

Wraps the `AuditRepository.list_by_org`. Admin-only.
"""

from __future__ import annotations

from platform.core.dependencies import CurrentUser, require_role
from platform.db.session import get_db
from platform.infrastructure.repositories.audit_repository import AuditRepository

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/admin/audit-logs", tags=["admin"])


@router.get("")
async def list_audit_logs(
    user: CurrentUser = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
    action: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
) -> list[dict]:
    repo = AuditRepository(db)
    rows = await repo.list_by_org(user.org_id, action=action, limit=limit)
    return [
        {
            "id": r.id,
            "actor_id": str(r.actor_id) if r.actor_id else None,
            "actor_type": r.actor_type,
            "action": r.action,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "ip": r.ip,
            "user_agent": r.user_agent,
            "payload": dict(r.payload or {}),
            "ts": r.ts.isoformat() if r.ts else None,
        }
        for r in rows
    ]
