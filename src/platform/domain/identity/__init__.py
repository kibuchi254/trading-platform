"""Identity bounded context — Organization, User, APIKey aggregates.

Pure-Python domain layer for tenancy, RBAC, and API-key lifecycle. The
aggregates here mirror the ORM in `platform/db/models/__init__.py` but contain
no SQLAlchemy. Persistence is handled by repositories in `infrastructure/`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID

from platform.core.exceptions import DomainError
from platform.domain.shared import AggregateRoot, DomainEvent, ValueObject


# ── Enums ───────────────────────────────────────────────────────────────────


class UserRole(StrEnum):
    """RBAC roles — checked via `User.can(action)` in the auth service."""
    ADMIN = "admin"
    TRADER = "trader"
    VIEWER = "viewer"
    BOT = "bot"


class PlanType(StrEnum):
    """Subscription tier — gates feature flags & rate limits."""
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


# ── Value objects ───────────────────────────────────────────────────────────


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class Email(ValueObject):
    """Lowercased, trimmed, regex-validated email address."""
    address: str

    def __post_init__(self) -> None:
        cleaned = self.address.strip().lower()
        if not _EMAIL_RE.match(cleaned):
            raise DomainError(f"Invalid email: {self.address}")
        object.__setattr__(self, "address", cleaned)

    def __str__(self) -> str:
        return self.address


@dataclass(frozen=True)
class APIKeyPrefix(ValueObject):
    """The first 8 characters of an API key — safe to display in UIs."""
    value: str

    def __post_init__(self) -> None:
        if len(self.value) != 8:
            raise DomainError("APIKeyPrefix must be exactly 8 characters")
        if not self.value.isalnum():
            raise DomainError("APIKeyPrefix must be alphanumeric")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Scopes(ValueObject):
    """An immutable set of permission scopes.

    `grant` and `revoke` return new Scopes (value-object semantics). Equality
    is order-independent — `Scopes(["a","b"]) == Scopes(["b","a"])`.
    """
    scopes: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_list(cls, items: list[str]) -> "Scopes":
        return cls(frozenset(items))

    def has(self, scope: str) -> bool:
        """True iff `scope` (or the wildcard `*`) is granted."""
        return "*" in self.scopes or scope in self.scopes

    def grant(self, scope: str) -> "Scopes":
        return Scopes(self.scopes | {scope})

    def revoke(self, scope: str) -> "Scopes":
        return Scopes(self.scopes - {scope})

    def to_list(self) -> list[str]:
        return sorted(self.scopes)


# ── Domain events ───────────────────────────────────────────────────────────


@dataclass(kw_only=True)
class OrgCreated(DomainEvent):
    org_id: UUID
    name: str
    plan: str


@dataclass(kw_only=True)
class OrgUpgraded(DomainEvent):
    org_id: UUID
    from_plan: str
    to_plan: str


@dataclass(kw_only=True)
class OrgDeactivated(DomainEvent):
    org_id: UUID


@dataclass(kw_only=True)
class UserCreated(DomainEvent):
    user_id: UUID
    org_id: UUID
    email: str
    role: str


@dataclass(kw_only=True)
class UserLoggedIn(DomainEvent):
    user_id: UUID


@dataclass(kw_only=True)
class UserRoleChanged(DomainEvent):
    user_id: UUID
    from_role: str
    to_role: str


@dataclass(kw_only=True)
class UserDeactivated(DomainEvent):
    user_id: UUID


@dataclass(kw_only=True)
class APIKeyCreated(DomainEvent):
    api_key_id: UUID
    org_id: UUID
    user_id: UUID
    key_prefix: str


@dataclass(kw_only=True)
class APIKeyUsed(DomainEvent):
    api_key_id: UUID


@dataclass(kw_only=True)
class APIKeyRevoked(DomainEvent):
    api_key_id: UUID


# ── Organization aggregate ─────────────────────────────────────────────────


@dataclass(kw_only=True)
class Organization(AggregateRoot):
    """A tenant on the platform. Owns users, API keys, terminals, etc."""
    name: str
    slug: str
    plan: PlanType = PlanType.FREE
    settings: dict = field(default_factory=dict)
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise DomainError("Organization name required")
        if not self.slug.strip():
            raise DomainError("Organization slug required")
        self.record_event(
            OrgCreated(org_id=self.id, name=self.name, plan=self.plan.value)
        )

    def upgrade_plan(self, new_plan: PlanType) -> None:
        """Move to a higher tier. FREE → PRO → ENTERPRISE only."""
        order = [PlanType.FREE, PlanType.PRO, PlanType.ENTERPRISE]
        if order.index(new_plan) <= order.index(self.plan):
            raise DomainError(
                f"Cannot upgrade {self.plan.value} → {new_plan.value} (not upward)"
            )
        from_plan = self.plan
        self.plan = new_plan
        self.record_event(
            OrgUpgraded(
                org_id=self.id,
                from_plan=from_plan.value, to_plan=new_plan.value,
            )
        )

    def update_settings(self, partial: dict) -> None:
        """Merge `partial` into `settings`. Does not replace the dict."""
        if not isinstance(partial, dict):
            raise DomainError("partial must be a dict")
        self.settings = {**self.settings, **partial}

    def deactivate(self) -> None:
        """Soft-deactivate the org — users cannot log in but data is retained."""
        if not self.is_active:
            return
        self.is_active = False
        self.record_event(OrgDeactivated(org_id=self.id))


# ── User aggregate ──────────────────────────────────────────────────────────


@dataclass(kw_only=True)
class User(AggregateRoot):
    """A platform user scoped to an Organization. Carries their own Scopes."""
    org_id: UUID
    email: Email
    display_name: str
    role: UserRole = UserRole.TRADER
    is_active: bool = True
    scopes: Scopes = field(default_factory=Scopes)
    last_login_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.display_name.strip():
            raise DomainError("display_name required")
        self.record_event(
            UserCreated(
                user_id=self.id, org_id=self.org_id,
                email=self.email.address, role=self.role.value,
            )
        )

    def login(self) -> None:
        """Record a successful login. Errors if the user is deactivated."""
        if not self.is_active:
            raise DomainError("User is deactivated; cannot log in")
        self.last_login_at = datetime.now(timezone.utc)
        self.record_event(UserLoggedIn(user_id=self.id))

    def change_role(self, new_role: UserRole) -> None:
        """Reassign the user's RBAC role. No-op if already that role."""
        if new_role == self.role:
            return
        from_role = self.role
        self.role = new_role
        self.record_event(
            UserRoleChanged(
                user_id=self.id,
                from_role=from_role.value, to_role=new_role.value,
            )
        )

    def activate(self) -> None:
        """Reverse a prior `deactivate()`."""
        self.is_active = True

    def deactivate(self) -> None:
        """Block future logins. Idempotent."""
        if not self.is_active:
            return
        self.is_active = False
        self.record_event(UserDeactivated(user_id=self.id))

    def grant_scope(self, scope: str) -> None:
        self.scopes = self.scopes.grant(scope)

    def revoke_scope(self, scope: str) -> None:
        self.scopes = self.scopes.revoke(scope)

    def can(self, action: str) -> bool:
        """Role-based capability check + explicit scope check."""
        role_caps = {
            UserRole.ADMIN: {"*"},
            UserRole.TRADER: {
                "order.place", "order.cancel", "position.close",
                "strategy.create", "strategy.activate", "terminal.sync",
            },
            UserRole.VIEWER: {"order.list", "position.list", "analytics.view"},
            UserRole.BOT: {"order.place", "order.cancel", "data.read"},
        }
        if "*" in role_caps.get(self.role, set()) or action in role_caps.get(self.role, set()):
            return True
        return self.scopes.has(action)


# ── APIKey aggregate ────────────────────────────────────────────────────────


@dataclass(kw_only=True)
class APIKey(AggregateRoot):
    """A long-lived API credential for a User. Hashed at rest; only the prefix
    is stored in plaintext for UI display.
    """
    org_id: UUID
    user_id: UUID
    name: str
    key_prefix: APIKeyPrefix
    key_hash: str
    scopes: Scopes = field(default_factory=Scopes)
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    is_revoked: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise DomainError("APIKey name required")
        if not self.key_hash:
            raise DomainError("APIKey key_hash required")
        self.record_event(
            APIKeyCreated(
                api_key_id=self.id, org_id=self.org_id, user_id=self.user_id,
                key_prefix=self.key_prefix.value,
            )
        )

    def touch(self) -> None:
        """Update `last_used_at` to now. Emits APIKeyUsed."""
        self.last_used_at = datetime.now(timezone.utc)
        self.record_event(APIKeyUsed(api_key_id=self.id))

    def revoke(self) -> None:
        """Permanently revoke the key. Idempotent."""
        if self.is_revoked:
            return
        self.is_revoked = True
        self.record_event(APIKeyRevoked(api_key_id=self.id))

    @property
    def is_expired(self) -> bool:
        """True iff `expires_at` is set and in the past."""
        if self.expires_at is None:
            return False
        return self.expires_at <= datetime.now(timezone.utc)

    @property
    def is_valid(self) -> bool:
        """True iff not revoked AND not expired."""
        return not self.is_revoked and not self.is_expired


__all__ = [
    "UserRole", "PlanType",
    "Email", "APIKeyPrefix", "Scopes",
    "OrgCreated", "OrgUpgraded", "OrgDeactivated",
    "UserCreated", "UserLoggedIn", "UserRoleChanged", "UserDeactivated",
    "APIKeyCreated", "APIKeyUsed", "APIKeyRevoked",
    "Organization", "User", "APIKey",
]
