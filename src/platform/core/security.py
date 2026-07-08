"""JWT issuance + verification, password hashing, API-key utilities."""
from __future__ import annotations

import secrets as _secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

import jwt
from passlib.context import CryptContext

from platform.core.config import get_settings

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)
Alg = Literal["HS256", "HS384", "HS512", "RS256"]


@dataclass(slots=True, frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = 0


def hash_password(raw: str) -> str:
    return _pwd.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return _pwd.verify(raw, hashed)


def _encode(payload: dict[str, object], ttl: int) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {**payload, "iat": now, "exp": now + timedelta(seconds=ttl)}
    return jwt.encode(
        payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def issue_token_pair(
    *,
    user_id: uuid.UUID,
    org_id: uuid.UUID,
    scopes: list[str] | None = None,
) -> TokenPair:
    settings = get_settings()
    base = {"sub": str(user_id), "org": str(org_id), "scopes": scopes or []}
    access = _encode({**base, "type": "access"}, settings.jwt_access_ttl_seconds)
    refresh = _encode({**base, "type": "refresh"}, settings.jwt_refresh_ttl_seconds)
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.jwt_access_ttl_seconds,
    )


def decode_token(token: str) -> dict[str, object]:
    """Verify + decode a JWT. Raises `jwt.PyJWTError` on failure."""
    settings = get_settings()
    return jwt.decode(
        token,
        settings.secret_key.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
    )


def generate_api_key() -> tuple[str, str]:
    """Return (raw_key, hashed_key). The raw key is shown once to the user;
    only the hashed form is persisted."""
    raw = f"atlas_{_secrets.token_urlsafe(32)}"
    return raw, _pwd.hash(raw)


def verify_api_key(raw: str, hashed: str) -> bool:
    return _pwd.verify(raw, hashed)
