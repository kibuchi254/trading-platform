"""Auth dependency — extracts user from JWT or API key."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform.core.security import decode_token, verify_api_key
from platform.db.models import APIKey, User
from platform.db.session import get_db


@dataclass(slots=True)
class CurrentUser:
    user_id: uuid.UUID
    org_id: uuid.UUID
    role: str
    scopes: list[str]
    auth_method: str  # jwt | api_key


async def get_current_user(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    if x_api_key:
        return await _auth_api_key(x_api_key, db)
    if authorization and authorization.lower().startswith("bearer "):
        return await _auth_jwt(authorization[7:], db)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing authentication",
    )


async def _auth_jwt(token: str, db: AsyncSession) -> CurrentUser:
    try:
        claims = decode_token(token)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=401, detail="Invalid token") from e
    if claims.get("type") != "access":
        raise HTTPException(status_code=401, detail="Wrong token type")
    user_id = uuid.UUID(str(claims["sub"]))
    org_id = uuid.UUID(str(claims["org"]))
    user = await db.get(User, user_id)
    if user is None or not user.is_active or user.is_deleted:
        raise HTTPException(status_code=401, detail="User inactive or deleted")
    return CurrentUser(
        user_id=user_id, org_id=org_id, role=user.role,
        scopes=list(claims.get("scopes", [])), auth_method="jwt",
    )


async def _auth_api_key(raw: str, db: AsyncSession) -> CurrentUser:
    # In production: hash the key and lookup by key_hash
    # Skeleton: linear scan by prefix
    prefix = raw[:8]
    stmt = select(APIKey).where(APIKey.key_prefix == prefix)
    result = await db.execute(stmt)
    api_key = result.scalar_one_or_none()
    if api_key is None or not verify_api_key(raw, api_key.key_hash):
        raise HTTPException(status_code=401, detail="Invalid API key")
    if api_key.expires_at is not None:
        from datetime import datetime, timezone
        if api_key.expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="API key expired")
    user = await db.get(User, api_key.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User inactive")
    return CurrentUser(
        user_id=user.id, org_id=api_key.org_id, role=user.role,
        scopes=list(api_key.scopes), auth_method="api_key",
    )


def require_role(*roles: str):  # type: ignore[no-untyped-def]
    """FastAPI dependency factory: require any of the given roles."""
    async def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles and "admin" not in user.scopes:
            raise HTTPException(status_code=403, detail="Insufficient role")
        return user
    return _dep
