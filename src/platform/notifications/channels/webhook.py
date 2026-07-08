"""Generic outbound webhook channel — signed JSON POST.

Designed for integrating ATLAS notifications into external automation
(Home Assistant, n8n, Slack incoming webhooks, custom internal endpoints).
Unlike the dedicated channels (email/telegram/discord) this channel is
URL-agnostic and lets the recipient decide how to render the payload.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any

import httpx

from platform.core.logging import get_logger
from platform.notifications.base import NotificationChannel

_log = get_logger(__name__)

_DEFAULT_TIMEOUT: float = 10.0
_SIGNATURE_HEADER: str = "X-ATLAS-Signature"
_USER_AGENT: str = "ATLAS-Notifications/1.0"


class WebhookChannel(NotificationChannel):
    """Generic outbound webhook — POSTs a JSON payload to any URL.

    Signing:
        If a ``secret`` is provided at construction, the raw JSON body is
        HMAC-SHA256-signed and the hex digest is sent in the
        ``X-ATLAS-Signature`` header. Recipients should recompute the
        digest over the raw request body to authenticate the sender.

    URL override:
        The ``to`` argument overrides the constructor's ``webhook_url``
        (per-message routing to different endpoints). If ``to`` is empty,
        the constructor default is used. If neither is set, ``send``
        returns ``False`` without a network call.

    Payload format:
        ``{"subject": ..., "body": ..., "ts": iso8601, "priority": ..., "meta": {...}}``

    Timeout:
        Defaults to 10 seconds (connect + read combined). Configurable
        via the ``timeout`` constructor argument.

    Returns:
        ``True`` on any HTTP 2xx response, ``False`` otherwise.
    """

    name = "webhook"

    def __init__(
        self,
        webhook_url: str = "",
        secret: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._webhook_url: str = webhook_url
        self._secret: str | None = secret
        # Caller-supplied headers override the defaults (Content-Type,
        # User-Agent). We copy to avoid mutating the caller's dict.
        self._headers: dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": _USER_AGENT,
            **(headers or {}),
        }
        self._timeout: float = timeout

    async def send(
        self,
        to: str,
        subject: str,
        body: str,
        *,
        priority: str = "NORMAL",
        meta: dict[str, Any] | None = None,
    ) -> bool:  # type: ignore[override]
        """POST the notification payload to the webhook.

        Args:
            to: Target URL — overrides the constructor default if non-empty.
            subject: Notification subject (forwarded as-is in payload).
            body: Notification body.
            priority: Priority string embedded in the payload. Defaults
                to ``"NORMAL"`` — direct callers can override. When
                invoked via the dispatcher (which uses the base 3-arg
                signature), this defaults to ``"NORMAL"``.
            meta: Optional metadata merged into the payload under the
                ``meta`` key.

        Returns:
            ``True`` on HTTP 2xx, ``False`` otherwise.
        """
        url = to or self._webhook_url
        if not url:
            _log.error("webhook_no_url")
            return False

        payload = self._build_payload(subject, body, priority, meta)
        raw = json.dumps(payload, default=str).encode("utf-8")
        headers = dict(self._headers)
        if self._secret:
            headers[_SIGNATURE_HEADER] = self._sign(raw, self._secret)

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, content=raw, headers=headers)
        except Exception:  # noqa: BLE001
            _log.exception("webhook_post_error", url=url)
            return False

        if 200 <= resp.status_code < 300:
            _log.info("webhook_sent", url=url, status=resp.status_code)
            return True

        _log.error(
            "webhook_send_failed",
            url=url,
            status=resp.status_code,
            body=resp.text[:300],
        )
        return False

    # ── Helpers ────────────────────────────────────────────────────────
    @staticmethod
    def _build_payload(
        subject: str,
        body: str,
        priority: str,
        meta: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Construct the outbound webhook payload.

        The ``ts`` field is the UTC ISO-8601 timestamp at the moment of
        sending — useful for recipients that need delivery-time audit.
        """
        return {
            "subject": subject,
            "body": body,
            "ts": datetime.now(timezone.utc).isoformat(),
            "priority": priority,
            "meta": meta or {},
        }

    @staticmethod
    def _sign(body: bytes, secret: str) -> str:
        """HMAC-SHA256 hex digest of ``body`` keyed with ``secret``.

        Returns a lowercase hex string suitable for direct comparison
        against the recipient's recomputed digest (constant-time compare
        on the recipient side is recommended).
        """
        return hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
