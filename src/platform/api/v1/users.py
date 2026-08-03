"""Users REST router (admin) — org user management.

Wraps the `create_user` command and exposes list / activate / deactivate for
org admins. All endpoints require the `admin` role.
"""

from __future__ import annotations

from datetime import UTC, datetime
from platform.application.commands.create_user import CreateUserCommand, handle_create_user
from platform.core.dependencies import CurrentUser, require_role
from platform.core.exceptions import NotFoundError
from platform.db.models import User
from platform.db.session import get_db
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/admin/users", tags=["admin"])


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str
    role: str = "trader"  # admin | trader | viewer | bot


class UserOut(BaseModel):
    id: UUID
    email: str
    display_name: str
    role: str
    is_active: bool
    last_login_at: str | None
    created_at: str

    model_config = {"from_attributes": True}


def _to_out(u: User) -> UserOut:
    return UserOut(
        id=u.id,
        email=u.email,
        display_name=u.display_name,
        role=u.role,
        is_active=u.is_active,
        last_login_at=u.last_login_at.isoformat() if u.last_login_at else None,
        created_at=u.created_at.isoformat() if u.created_at else None,
    )


@router.get("", response_model=list[UserOut])
async def list_users(
    user: CurrentUser = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> list[UserOut]:
    stmt = select(User).where(User.org_id == user.org_id, User.deleted_at.is_(None))
    rows = (await db.execute(stmt)).scalars().all()
    return [_to_out(r) for r in rows]


@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    req: UserCreate,
    user: CurrentUser = Depends(require_role("admin")),
) -> UserOut:
    result = await handle_create_user(
        CreateUserCommand(
            org_id=user.org_id,
            email=req.email,
            password=req.password,
            display_name=req.display_name,
            role=req.role,
        )
    )
    # Re-read to get timestamps
    from platform.db.session import db_context

    async with db_context() as db:
        u = await db.get(User, result.id)
        return _to_out(u)  # type: ignore[arg-type]


@router.patch("/{user_id}/activate", response_model=UserOut)
async def activate_user(
    user_id: UUID,
    user: CurrentUser = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    u = await db.get(User, user_id)
    if u is None or u.org_id != user.org_id:
        raise NotFoundError(f"User {user_id} not found")
    u.is_active = True
    u.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(u)
    return _to_out(u)


@router.patch("/{user_id}/deactivate", response_model=UserOut)
async def deactivate_user(
    user_id: UUID,
    user: CurrentUser = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    u = await db.get(User, user_id)
    if u is None or u.org_id != user.org_id:
        raise NotFoundError(f"User {user_id} not found")
    u.is_active = False
    u.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(u)
    return _to_out(u)
