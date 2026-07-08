"""Test the Identity domain — Organization, User, APIKey aggregates."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from platform.core.exceptions import DomainError
from platform.domain.identity import (
    APIKey,
    APIKeyPrefix,
    Email,
    Organization,
    PlanType,
    Scopes,
    User,
    UserRole,
)


# ── Email value object ───────────────────────────────────────────────────────


def test_email_normalizes_to_lowercase_and_strips() -> None:
    """Email is lowercased and trimmed on construction."""
    e = Email(address="  John.Doe@Example.COM  ")
    assert e.address == "john.doe@example.com"


def test_email_rejects_invalid_format() -> None:
    """Email addresses must match a basic regex."""
    with pytest.raises(DomainError):
        Email(address="not-an-email")
    with pytest.raises(DomainError):
        Email(address="missing@domain")


# ── APIKeyPrefix value object ────────────────────────────────────────────────


def test_api_key_prefix_requires_eight_alphanumeric_chars() -> None:
    """APIKeyPrefix must be exactly 8 alphanumeric characters."""
    APIKeyPrefix(value="abcdef12")  # OK
    with pytest.raises(DomainError):
        APIKeyPrefix(value="short")
    with pytest.raises(DomainError):
        APIKeyPrefix(value="abcdef123")  # 9 chars
    with pytest.raises(DomainError):
        APIKeyPrefix(value="abcdef!@")  # non-alphanumeric


# ── Scopes value object ──────────────────────────────────────────────────────


def test_scopes_has_with_wildcard_or_explicit() -> None:
    """'*' wildcard grants every scope; explicit grants one."""
    wild = Scopes.from_list(["*"])
    assert wild.has("any.scope")
    explicit = Scopes.from_list(["order.place"])
    assert explicit.has("order.place")
    assert not explicit.has("order.cancel")


def test_scopes_grant_and_revoke_return_new_instances() -> None:
    """Scopes is immutable — grant/revoke return new instances."""
    s0 = Scopes.from_list(["a"])
    s1 = s0.grant("b")
    assert s0.to_list() == ["a"]
    assert s1.to_list() == ["a", "b"]
    s2 = s1.revoke("a")
    assert s2.to_list() == ["b"]


def test_scopes_equality_is_order_independent() -> None:
    """Scopes(["a","b"]) == Scopes(["b","a"]) — set semantics."""
    assert Scopes.from_list(["a", "b"]) == Scopes.from_list(["b", "a"])


# ── Organization aggregate ───────────────────────────────────────────────────


def _make_org() -> Organization:
    return Organization(name="Acme Capital", slug="acme-capital")


def test_org_starts_on_free_plan_and_emits_created_event() -> None:
    """New org defaults to FREE and emits OrgCreated."""
    org = _make_org()
    assert org.plan == PlanType.FREE
    assert org.is_active is True
    events = org.collect_events()
    assert len(events) == 1
    assert events[0].__class__.__name__ == "OrgCreated"


def test_org_upgrade_plan_raises_tier() -> None:
    """FREE → PRO → ENTERPRISE upgrades work."""
    org = _make_org()
    org.upgrade_plan(PlanType.PRO)
    assert org.plan == PlanType.PRO
    org.upgrade_plan(PlanType.ENTERPRISE)
    assert org.plan == PlanType.ENTERPRISE


def test_org_upgrade_plan_rejects_downgrade() -> None:
    """Cannot downgrade via upgrade_plan."""
    org = _make_org()
    org.upgrade_plan(PlanType.ENTERPRISE)
    with pytest.raises(DomainError):
        org.upgrade_plan(PlanType.PRO)


def test_org_update_settings_merges_partial() -> None:
    """update_settings merges, not replaces."""
    org = _make_org()
    org.update_settings({"theme": "dark"})
    org.update_settings({"locale": "en-US"})
    assert org.settings["theme"] == "dark"
    assert org.settings["locale"] == "en-US"


def test_org_update_settings_rejects_non_dict() -> None:
    """A non-dict partial raises DomainError."""
    org = _make_org()
    with pytest.raises(DomainError):
        org.update_settings("not-a-dict")  # type: ignore[arg-type]


def test_org_deactivate_is_idempotent() -> None:
    """Deactivating an already-deactivated org is a no-op."""
    org = _make_org()
    org.deactivate()
    assert org.is_active is False
    org.deactivate()  # second call should not raise


def test_org_requires_name_and_slug() -> None:
    """Empty name or slug raises DomainError."""
    with pytest.raises(DomainError):
        Organization(name="", slug="x")
    with pytest.raises(DomainError):
        Organization(name="x", slug="")


# ── User aggregate ───────────────────────────────────────────────────────────


def _make_user(role: UserRole = UserRole.TRADER) -> User:
    return User(
        org_id=uuid4(), email=Email(address="trader@example.com"),
        display_name="Trader Joe", role=role,
    )


def test_user_starts_active_and_emits_created_event() -> None:
    """Fresh users are active and emit UserCreated."""
    u = _make_user()
    assert u.is_active is True
    events = u.collect_events()
    assert len(events) == 1
    assert events[0].__class__.__name__ == "UserCreated"


def test_user_login_stamps_last_login_and_emits_event() -> None:
    """login() records last_login_at and emits UserLoggedIn."""
    u = _make_user()
    u.collect_events()  # drain UserCreated
    u.login()
    assert u.last_login_at is not None
    events = u.collect_events()
    assert any(e.__class__.__name__ == "UserLoggedIn" for e in events)


def test_user_login_blocked_when_deactivated() -> None:
    """A deactivated user cannot log in."""
    u = _make_user()
    u.deactivate()
    with pytest.raises(DomainError):
        u.login()


def test_user_change_role_emits_event() -> None:
    """Changing role emits UserRoleChanged."""
    u = _make_user(UserRole.VIEWER)
    u.collect_events()
    u.change_role(UserRole.TRADER)
    assert u.role == UserRole.TRADER
    events = u.collect_events()
    assert any(e.__class__.__name__ == "UserRoleChanged" for e in events)


def test_user_change_role_to_same_is_noop() -> None:
    """Changing to the same role does nothing."""
    u = _make_user(UserRole.TRADER)
    u.collect_events()
    u.change_role(UserRole.TRADER)
    events = u.collect_events()
    assert events == []


def test_user_can_admin_does_everything() -> None:
    """ADMIN role has the wildcard capability set."""
    u = _make_user(UserRole.ADMIN)
    assert u.can("any.action.ever")


def test_user_can_trader_specific_actions_only() -> None:
    """TRADER can place orders but cannot list analytics."""
    u = _make_user(UserRole.TRADER)
    assert u.can("order.place")
    assert not u.can("analytics.view")


def test_user_can_viewer_can_list_only() -> None:
    """VIEWER is read-only — can list, cannot place."""
    u = _make_user(UserRole.VIEWER)
    assert u.can("order.list")
    assert not u.can("order.place")


def test_user_grant_and_revoke_scope() -> None:
    """Explicit scope grants extend role capabilities."""
    u = _make_user(UserRole.VIEWER)
    assert not u.can("custom.action")
    u.grant_scope("custom.action")
    assert u.can("custom.action")
    u.revoke_scope("custom.action")
    assert not u.can("custom.action")


def test_user_requires_display_name() -> None:
    """Empty display_name raises DomainError."""
    with pytest.raises(DomainError):
        User(org_id=uuid4(), email=Email(address="x@example.com"),
             display_name="   ")


# ── APIKey aggregate ─────────────────────────────────────────────────────────


def _make_apikey() -> APIKey:
    return APIKey(
        org_id=uuid4(), user_id=uuid4(), name="prod-key",
        key_prefix=APIKeyPrefix(value="atlas123"),
        key_hash="$2b$12$somefakehashfor testing purposes only abcd",
    )


def test_apikey_starts_valid_and_emits_created_event() -> None:
    """Fresh APIKey is valid (not revoked, not expired)."""
    k = _make_apikey()
    assert k.is_valid is True
    assert k.is_revoked is False
    events = k.collect_events()
    assert len(events) == 1
    assert events[0].__class__.__name__ == "APIKeyCreated"


def test_apikey_revoke_marks_invalid_idempotently() -> None:
    """revoked keys are invalid; double-revoke is a no-op."""
    k = _make_apikey()
    k.revoke()
    assert k.is_revoked is True
    assert k.is_valid is False
    k.revoke()  # should not raise


def test_apikey_is_expired_when_expires_at_in_past() -> None:
    """An expired key is invalid even if not revoked."""
    k = APIKey(
        org_id=uuid4(), user_id=uuid4(), name="expired-key",
        key_prefix=APIKeyPrefix(value="atlas456"),
        key_hash="hashvalue",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    assert k.is_expired is True
    assert k.is_valid is False


def test_apikey_not_expired_when_expires_at_in_future() -> None:
    """Future expiry → key still valid."""
    k = APIKey(
        org_id=uuid4(), user_id=uuid4(), name="future-key",
        key_prefix=APIKeyPrefix(value="atlas789"),
        key_hash="hashvalue",
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    assert k.is_expired is False
    assert k.is_valid is True


def test_apikey_touch_updates_last_used_and_emits_event() -> None:
    """touch() stamps last_used_at and emits APIKeyUsed."""
    k = _make_apikey()
    k.collect_events()
    k.touch()
    assert k.last_used_at is not None
    events = k.collect_events()
    assert any(e.__class__.__name__ == "APIKeyUsed" for e in events)


def test_apikey_requires_name_and_hash() -> None:
    """Empty name or hash raises DomainError."""
    with pytest.raises(DomainError):
        APIKey(org_id=uuid4(), user_id=uuid4(), name="",
               key_prefix=APIKeyPrefix(value="atlas001"), key_hash="x")
    with pytest.raises(DomainError):
        APIKey(org_id=uuid4(), user_id=uuid4(), name="x",
               key_prefix=APIKeyPrefix(value="atlas001"), key_hash="")
