"""Discord webhook notification channel.

Posts to a Discord channel via an incoming webhook URL. The webhook is
per-channel (one URL → one channel), so the ``to`` argument is accepted
for API parity but ignored.
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from platform.core.config import get_settings
from platform.core.logging import get_logger
from platform.notifications.base import NotificationChannel

_log = get_logger(__name__)

# Discord embed colors (decimal RGB).
_COLOR_GREEN: int = 0x2ECC71   # success
_COLOR_RED: int = 0xE74C3C     # error / critical
_COLOR_AMBER: int = 0xF1C40F   # warning
_COLOR_BLUE: int = 0x3498DB    # info / default

# Discord embed length limits.
_EMBED_TITLE_MAX: int = 256
_EMBED_DESC_MAX: int = 4096
_CONTENT_MAX: int = 2000

# Cap for how long we are willing to sleep on a single rate-limit event.
_RATE_LIMIT_SLEEP_CAP: float = 30.0


class DiscordChannel(NotificationChannel):
    """Discord webhook channel.

    Configuration:
        ``discord_webhook_url`` — full Discord webhook URL (HttpUrl | None).

    Embeds:
        If ``subject`` is non-empty, the message is sent as a Discord embed
        with ``title=subject`` and ``description=body``. Otherwise the body
        is sent as plain ``content`` (≤ 2000 chars — Discord limit).

    Color coding:
        Inferred from the message text (case-insensitive substring match
        against keywords). Mapping:

            - RED    — ``critical``, ``error``, ``fail``
            - AMBER  — ``warning``, ``warn``, ``high``
            - GREEN  — ``success``, ``ok``, ``filled``, ``low``
            - BLUE   — anything else (default / info)

    Rate limiting:
        Discord returns ``X-RateLimit-Remaining`` and
        ``X-RateLimit-Reset-After`` headers. When ``Remaining`` hits 0
        after a successful post, the channel sleeps for the reset window
        before returning, so the next message does not 429. An explicit
        HTTP 429 response is handled by reading ``retry_after`` from the
        JSON body and sleeping that long.

    Note:
        The ``to`` argument is ignored — Discord webhooks are per-channel
        (one URL → one channel). It is accepted for API parity with other
        channels.
    """

    name = "discord"

    def __init__(self, timeout: float = 15.0) -> None:
        settings = get_settings()
        webhook = settings.discord_webhook_url
        if webhook is None:
            raise RuntimeError("DISCORD_WEBHOOK_URL not configured")
        self._webhook_url: str = str(webhook)
        self._timeout: float = timeout

    async def send(self, to: str, subject: str, body: str) -> bool:
        """Send a Discord message via webhook.

        Args:
            to: Ignored — Discord webhooks are channel-scoped.
            subject: If non-empty, sent as embed title.
            body: Embed description (when subject is set) or plain content.

        Returns:
            ``True`` on success (HTTP 200/204), ``False`` on failure.
        """
        color = self._color_for(f"{subject} {body}")
        payload = self._build_payload(subject, body, color)
        try:
            return await self._post_with_rate_limit(payload)
        except Exception:  # noqa: BLE001
            _log.exception("discord_send_error")
            return False

    # ── Helpers ────────────────────────────────────────────────────────
    def _build_payload(
        self,
        subject: str,
        body: str,
        color: int,
    ) -> dict[str, Any]:
        """Build the Discord webhook JSON payload.

        Chooses embed (when subject is present) vs plain content.
        """
        if subject:
            return {
                "embeds": [
                    {
                        "title": subject[:_EMBED_TITLE_MAX],
                        "description": body[:_EMBED_DESC_MAX],
                        "color": color,
                    }
                ]
            }
        return {"content": body[:_CONTENT_MAX]}

    @staticmethod
    def _color_for(text: str) -> int:
        """Infer embed color from message content via keyword matching.

        Order matters — RED (most severe) is checked first so that
        ``"critical warning"`` is classified as RED, not AMBER.
        """
        t = text.lower()
        if any(k in t for k in ("critical", "error", "fail")):
            return _COLOR_RED
        if any(k in t for k in ("warning", "warn", "high")):
            return _COLOR_AMBER
        if any(k in t for k in ("success", "ok", "filled", "low")):
            return _COLOR_GREEN
        return _COLOR_BLUE

    async def _post_with_rate_limit(self, payload: dict[str, Any]) -> bool:
        """POST to the webhook, honoring Discord rate-limit headers.

        Strategy:
            - On HTTP 200/204: log success, then politely sleep if the
              response indicates we just exhausted our budget
              (``X-RateLimit-Remaining == 0``) so the next call from the
              caller doesn't 429.
            - On HTTP 429: read ``retry_after`` from the JSON body and
              sleep, then retry (up to 3 attempts).
            - On HTTP 5xx: short linear backoff + retry.
            - On other 4xx: log and give up (client error — retrying
              won't help).
        """
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for attempt in range(3):
                try:
                    resp = await client.post(self._webhook_url, json=payload)
                except Exception:  # noqa: BLE001
                    _log.exception("discord_post_error", attempt=attempt)
                    return False

                if resp.status_code in (200, 204):
                    wait = self._quota_wait_seconds(resp.headers)
                    if wait > 0:
                        _log.info("discord_quota_wait", wait=wait)
                        await asyncio.sleep(wait)
                    _log.info("discord_sent")
                    return True

                if resp.status_code == 429:
                    retry_after = self._parse_retry_after(resp)
                    _log.warning(
                        "discord_rate_limited",
                        retry_after=retry_after,
                        attempt=attempt,
                    )
                    await asyncio.sleep(min(retry_after, _RATE_LIMIT_SLEEP_CAP))
                    continue

                _log.error(
                    "discord_send_failed",
                    status=resp.status_code,
                    body=resp.text[:300],
                    attempt=attempt,
                )
                if resp.status_code >= 500 and attempt < 2:
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue
                return False
        return False

    @staticmethod
    def _quota_wait_seconds(headers: Any) -> float:
        """Return how long to sleep based on remaining quota, or 0.

        If ``X-RateLimit-Remaining`` is ``"0"`` and
        ``X-RateLimit-Reset-After`` is present, returns that value
        (capped at 60s). Otherwise returns 0.
        """
        remaining = headers.get("X-RateLimit-Remaining")
        reset_after = headers.get("X-RateLimit-Reset-After")
        if remaining == "0" and reset_after is not None:
            try:
                wait = float(reset_after)
            except (TypeError, ValueError):
                return 0.0
            return min(max(wait, 0.0), 60.0)
        return 0.0

    @staticmethod
    def _parse_retry_after(resp: httpx.Response) -> float:
        """Extract ``retry_after`` from a 429 response body.

        Falls back to 1.0s if the body is not JSON or the field is
        missing — never raises.
        """
        try:
            data = resp.json()
            return float(data.get("retry_after", 1.0))
        except Exception:  # noqa: BLE001
            return 1.0
