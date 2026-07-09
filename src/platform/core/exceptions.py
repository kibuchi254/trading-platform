"""Platform exception hierarchy. Maps cleanly to HTTP status codes via FastAPI handlers."""

from __future__ import annotations


class PlatformError(Exception):
    """Base class. Carries a code + http_status for the global exception handler."""

    code: str = "platform.error"
    http_status: int = 500

    def __init__(
        self, message: str = "", *, code: str | None = None, http_status: int | None = None
    ) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        if code:
            self.code = code
        if http_status:
            self.http_status = http_status


# ── 4xx ────────────────────────────────────────────────────────────────────
class ValidationError(PlatformError):
    code = "platform.validation"
    http_status = 422


class NotFoundError(PlatformError):
    code = "platform.not_found"
    http_status = 404


class ConflictError(PlatformError):
    code = "platform.conflict"
    http_status = 409


class AuthenticationError(PlatformError):
    code = "platform.auth"
    http_status = 401


class AuthorizationError(PlatformError):
    code = "platform.forbidden"
    http_status = 403


class RateLimitError(PlatformError):
    code = "platform.rate_limit"
    http_status = 429


# ── Domain errors ──────────────────────────────────────────────────────────
class DomainError(PlatformError):
    code = "platform.domain"
    http_status = 400


class RiskLimitBreached(DomainError):
    code = "platform.risk.breach"


class StrategyRejected(DomainError):
    code = "platform.strategy.rejected"


class BridgeError(PlatformError):
    code = "platform.bridge"
    http_status = 502


class TerminalOffline(BridgeError):
    code = "platform.bridge.terminal_offline"


class CommandTimeout(BridgeError):
    code = "platform.bridge.command_timeout"
    http_status = 504


# ── 5xx ────────────────────────────────────────────────────────────────────
class InfrastructureError(PlatformError):
    code = "platform.infrastructure"
    http_status = 503
