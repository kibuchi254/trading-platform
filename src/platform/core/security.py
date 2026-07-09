"""JWT issuance + verification, password hashing, API-key utilities."""

from __future__ import annotations

import secrets as _secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from platform.core.config import get_settings
from typing import Literal

import bcrypt
import jwt

Alg = Literal["HS256", "HS384", "HS512", "RS256"]


@dataclass(slots=True, frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = 0


def hash_password(raw: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(raw.encode("utf-8"), salt).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _encode(payload: dict[str, object], ttl: int) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
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
    return raw, hash_password(raw)


def verify_api_key(raw: str, hashed: str) -> bool:
    return verify_password(raw, hashed)
