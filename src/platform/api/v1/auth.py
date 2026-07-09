"""Auth router — login, refresh, API key generation."""

from __future__ import annotations

from datetime import UTC, datetime
from platform.core.dependencies import CurrentUser, get_current_user
from platform.core.security import (
    generate_api_key,
    issue_token_pair,
    verify_password,
)
from platform.db.models import APIKey, User
from platform.db.session import get_db
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class APIKeyOut(BaseModel):
    id: UUID
    name: str
    key_prefix: str
    raw_key: str  # shown ONCE
    scopes: list[str]


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    user = (await db.execute(select(User).where(User.email == req.email))).scalar_one_or_none()
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active or user.is_deleted:
        raise HTTPException(status_code=401, detail="Account disabled")
    user.last_login_at = datetime.now(UTC)
    await db.commit()
    pair = issue_token_pair(user_id=user.id, org_id=user.org_id, scopes=[user.role])
    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        token_type=pair.token_type,
        expires_in=pair.expires_in,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest) -> TokenResponse:
    from platform.core.security import decode_token

    try:
        claims = decode_token(req.refresh_token)
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid refresh token") from e
    if claims.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Not a refresh token")
    pair = issue_token_pair(
        user_id=UUID(str(claims["sub"])),
        org_id=UUID(str(claims["org"])),
        scopes=list(claims.get("scopes", [])),
    )
    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        token_type=pair.token_type,
        expires_in=pair.expires_in,
    )


@router.post("/api-keys", response_model=APIKeyOut)
async def create_api_key(
    name: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> APIKeyOut:
    raw, hashed = generate_api_key()
    api_key = APIKey(
        org_id=user.org_id,
        user_id=user.user_id,
        name=name,
        key_prefix=raw[:8],
        key_hash=hashed,
        scopes=[user.role],
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)
    return APIKeyOut(
        id=api_key.id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        raw_key=raw,
        scopes=api_key.scopes,
    )
