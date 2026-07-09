"""Create a new user."""

from __future__ import annotations

from platform.core.exceptions import ConflictError
from platform.core.security import hash_password
from platform.db.models import Organization, User
from platform.db.session import db_context
from uuid import UUID, uuid4

from pydantic import BaseModel, EmailStr
from sqlalchemy import select


class CreateUserCommand(BaseModel):
    org_id: UUID
    email: EmailStr
    password: str
    display_name: str
    role: str = "trader"


class CreateUserResult(BaseModel):
    id: UUID
    email: str
    display_name: str
    role: str


async def handle_create_user(cmd: CreateUserCommand) -> CreateUserResult:
    async with db_context() as db:
        # Check email uniqueness
        existing = (
            await db.execute(select(User).where(User.email == cmd.email.lower()))
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError(f"User with email {cmd.email} already exists")
        # Verify org exists
        org = await db.get(Organization, cmd.org_id)
        if org is None:
            raise ConflictError(f"Organization {cmd.org_id} not found")

        u = User(
            id=uuid4(),
            org_id=cmd.org_id,
            email=cmd.email.lower(),
            password_hash=hash_password(cmd.password),
            display_name=cmd.display_name,
            role=cmd.role,
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return CreateUserResult(
            id=u.id,
            email=u.email,
            display_name=u.display_name,
            role=u.role,
        )
