"""Structured JSON logging via structlog, with correlation IDs and redaction."""

from __future__ import annotations

import logging
import sys
from platform.core.config import get_settings
from typing import Any

import structlog
from structlog.types import EventDict, Processor


def _add_app_context(_logger: Any, _method: str, event_dict: EventDict) -> EventDict:
    settings = get_settings()
    event_dict.setdefault("app", settings.app_name)
    event_dict.setdefault("env", settings.env)
    return event_dict


def _redact_secrets(_logger: Any, _method: str, event_dict: EventDict) -> EventDict:
    """Mask values whose keys look like secrets."""
    sensitive = {"password", "secret", "token", "api_key", "authorization", "refresh_token"}
    for key in list(event_dict):
        if any(s in key.lower() for s in sensitive):
            event_dict[key] = "***REDACTED***"
    return event_dict


def configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_app_context,
        _redact_secrets,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if settings.is_production:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
