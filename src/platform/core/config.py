"""Centralized Pydantic settings for the ATLAS platform."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # ── Runtime ──────────────────────────────────────────────────────────
    app_name: str = "atlas"
    env: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    secret_key: SecretStr = SecretStr("change-me")
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_seconds: int = 900
    jwt_refresh_ttl_seconds: int = 2_592_000

    # ── HTTP / API ───────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"

    # ── MT5 Bridge ───────────────────────────────────────────────────────
    bridge_host: str = "0.0.0.0"
    bridge_port: int = 9000
    bridge_auth_token: SecretStr = SecretStr("change-me-bridge-token")
    bridge_heartbeat_timeout_seconds: int = 30
    bridge_reconnect_grace_seconds: int = 10

    # ── Database ─────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://atlas:atlas@localhost:5432/atlas"
    database_pool_size: int = 20
    database_max_overflow: int = 20

    # ── Redis / Celery ───────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # ── LLM ──────────────────────────────────────────────────────────────
    llm_provider: Literal["openai", "anthropic", "vllm", "ollama", "none"] = "none"
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: HttpUrl | None = None
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: int = 30

    # ── Telemetry ────────────────────────────────────────────────────────
    otel_exporter_otlp_endpoint: str | None = "http://localhost:4317"
    prometheus_metrics_port: int = 9090

    # ── Notifications ────────────────────────────────────────────────────
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    telegram_bot_token: SecretStr | None = None
    discord_webhook_url: HttpUrl | None = None

    # ── Derived ──────────────────────────────────────────────────────────
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @field_validator("secret_key")
    @classmethod
    def _validate_secret(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 16:
            raise ValueError("SECRET_KEY must be at least 16 characters")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor — used as FastAPI dependency."""
    return Settings()
