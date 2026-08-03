"""Notifications REST router — the in-app notification feed.

Lists notification rows for the org (optionally the calling user only).
Org-scoped via the authenticated user.
"""

from __future__ import annotations

from platform.core.dependencies import CurrentUser, get_current_user
from platform.db.models import Notification
from platform.db.session import get_db
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    channel: str | None = Query(default=None),
    status: str | None = Query(default=None),
    mine: bool = Query(default=False),
    limit: int = Query(default=100, le=500),
) -> list[dict]:
    stmt = select(Notification).where(Notification.org_id == user.org_id)
    if mine:
        stmt = stmt.where(Notification.user_id == user.user_id)
    if channel:
        stmt = stmt.where(Notification.channel == channel)
    if status:
        stmt = stmt.where(Notification.status == status)
    stmt = stmt.order_by(Notification.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(r.id),
            "user_id": str(r.user_id) if r.user_id else None,
            "channel": r.channel,
            "subject": r.subject,
            "body": r.body,
            "status": r.status,
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            "error": r.error,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
