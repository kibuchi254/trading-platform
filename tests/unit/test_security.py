"""Test security utilities — JWT, API key, password hashing."""
from __future__ import annotations

import uuid

import pytest

from platform.core.security import (
    decode_token, generate_api_key, hash_password, issue_token_pair,
    verify_api_key, verify_password,
)


def test_password_hash_and_verify() -> None:
    raw = "MySecurePassword123!"
    hashed = hash_password(raw)
    assert hashed != raw
    assert verify_password(raw, hashed)
    assert not verify_password("wrong", hashed)


def test_password_hash_is_unique_per_call() -> None:
    raw = "SamePassword"
    h1 = hash_password(raw)
    h2 = hash_password(raw)
    assert h1 != h2  # bcrypt salt
    assert verify_password(raw, h1)
    assert verify_password(raw, h2)


def test_jwt_issue_and_decode() -> None:
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    pair = issue_token_pair(user_id=user_id, org_id=org_id, scopes=["trader"])
    assert pair.access_token
    assert pair.refresh_token
    assert pair.token_type == "Bearer"

    claims = decode_token(pair.access_token)
    assert claims["sub"] == str(user_id)
    assert claims["org"] == str(org_id)
    assert claims["type"] == "access"
    assert "trader" in claims["scopes"]


def test_jwt_refresh_token_has_correct_type() -> None:
    pair = issue_token_pair(user_id=uuid.uuid4(), org_id=uuid.uuid4())
    claims = decode_token(pair.refresh_token)
    assert claims["type"] == "refresh"


def test_jwt_invalid_token_raises() -> None:
    import jwt
    with pytest.raises(jwt.PyJWTError):
        decode_token("invalid.token.here")


def test_api_key_generate_and_verify() -> None:
    raw, hashed = generate_api_key()
    assert raw.startswith("atlas_")
    assert hashed != raw
    assert verify_api_key(raw, hashed)
    assert not verify_api_key("atlas_wrong", hashed)


def test_api_key_uniqueness() -> None:
    raw1, _ = generate_api_key()
    raw2, _ = generate_api_key()
    assert raw1 != raw2
