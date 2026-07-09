"""Telegram notification channel — Bot API via ``httpx``.

Sends messages, photos, and chart screenshots through the Telegram Bot API.
Configuration is sourced from ``Settings.telegram_bot_token`` (SecretStr).
"""

from __future__ import annotations

from platform.core.config import get_settings
from platform.core.logging import get_logger
from platform.notifications.base import NotificationChannel
from typing import Any

import httpx

_log = get_logger(__name__)

# Telegram hard limit per message — see Bot API docs.
_TG_MAX_LEN: int = 4096
# Caption length limit for sendPhoto.
_TG_CAPTION_MAX_LEN: int = 1024
# Base URL template for Bot API calls.
_TG_API_BASE: str = "https://api.telegram.org/bot{token}/{method}"


class TelegramChannel(NotificationChannel):
    """Async Telegram Bot API channel.

    Configuration:
        ``telegram_bot_token`` — bot token from ``@BotFather`` (SecretStr).

    Formatting:
        Messages are sent with ``parse_mode=MarkdownV2``. Callers must
        escape Markdown-sensitive characters themselves (see Telegram docs:
        https://core.telegram.org/bots/api#markdownv2-style). If the API
        rejects the Markdown payload (HTTP 400), the channel automatically
        retries as plain text so the message still lands.

    Long messages:
        Bodies longer than 4096 chars are split into ordered chunks at
        newline boundaries when possible (hard-wrap otherwise), and each
        chunk is prefixed with ``[i/N]`` so the chat client displays them
        in order.

    Photos:
        :meth:`send_photo` accepts a publicly reachable photo URL — used
        for chart screenshots, trade visualisations, and report banners.
    """

    name = "telegram"

    def __init__(self, timeout: float = 15.0) -> None:
        settings = get_settings()
        token = settings.telegram_bot_token
        if token is None:
            raise RuntimeError("TELEGRAM_BOT_TOKEN not configured")
        self._token: str = token.get_secret_value()
        self._timeout: float = timeout

    # ── Public API ─────────────────────────────────────────────────────
    async def send(self, to: str, subject: str, body: str) -> bool:
        """Send a Markdown-formatted message to chat_id ``to``.

        Args:
            to: Telegram chat_id (numeric string) or ``@channelname``.
            subject: Prepended as a bold Markdown title (``*subject*``).
                Empty string → body only.
            body: Message body in MarkdownV2.

        Returns:
            ``True`` if every chunk was delivered, ``False`` otherwise.
            A single chunk failure does not abort the remaining chunks
            (best-effort delivery), but the return value reflects any
            failure.
        """
        full = f"*{subject}*\n{body}" if subject else body
        chunks = self._split(full)
        all_ok = True
        total = len(chunks)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for idx, chunk in enumerate(chunks, start=1):
                if total > 1:
                    chunk = f"[{idx}/{total}] {chunk}"
                if not await self._send_message(client, to, chunk):
                    all_ok = False
        return all_ok

    async def send_photo(
        self,
        chat_id: str,
        photo_url: str,
        caption: str = "",
    ) -> bool:
        """Send a photo by URL to a chat.

        Useful for chart screenshots, trade visualisations, and daily
        performance reports. The image is not downloaded by the bot —
        Telegram fetches the URL server-side.

        Args:
            chat_id: Target chat (same format as ``to`` in :meth:`send`).
            photo_url: Publicly reachable image URL.
            caption: Optional caption in MarkdownV2. Truncated to 1024
                chars per Telegram limit.

        Returns:
            ``True`` on success, ``False`` on failure.
        """
        url = _TG_API_BASE.format(token=self._token, method="sendPhoto")
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "photo": photo_url,
        }
        if caption:
            payload["caption"] = caption[:_TG_CAPTION_MAX_LEN]
            payload["parse_mode"] = "MarkdownV2"

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload)
        except Exception:
            _log.exception("telegram_photo_error", chat_id=chat_id)
            return False

        if resp.status_code == 200:
            _log.info("telegram_photo_sent", chat_id=chat_id)
            return True

        _log.error(
            "telegram_photo_failed",
            chat_id=chat_id,
            status=resp.status_code,
            body=resp.text[:300],
        )
        return False

    # ── Helpers ────────────────────────────────────────────────────────
    async def _send_message(
        self,
        client: httpx.AsyncClient,
        chat_id: str,
        text: str,
    ) -> bool:
        """POST a single ``sendMessage`` call.

        Tries MarkdownV2 first; on a 400 (parse error) falls back to plain
        text so the message still lands. Other 4xx / 5xx are logged and
        surfaced as failures.
        """
        url = _TG_API_BASE.format(token=self._token, method="sendMessage")
        for parse_mode in ("MarkdownV2", None):
            payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
            if parse_mode:
                payload["parse_mode"] = parse_mode
            try:
                resp = await client.post(url, json=payload)
            except Exception:
                _log.exception("telegram_send_error", chat_id=chat_id)
                return False

            if resp.status_code == 200:
                return True

            body = resp.text[:300]
            if resp.status_code == 400 and parse_mode is not None:
                _log.warning(
                    "telegram_markdown_retry_plain",
                    chat_id=chat_id,
                    body=body,
                )
                continue

            _log.error(
                "telegram_send_failed",
                chat_id=chat_id,
                status=resp.status_code,
                body=body,
            )
            return False
        return False

    @staticmethod
    def _split(text: str, size: int = _TG_MAX_LEN) -> list[str]:
        """Split ``text`` into chunks of at most ``size`` chars.

        Splits at newline boundaries when possible to avoid tearing
        paragraphs. Single lines longer than ``size`` are hard-wrapped.
        """
        if len(text) <= size:
            return [text]

        chunks: list[str] = []
        buf: str = ""
        for line in text.splitlines(keepends=True):
            if len(buf) + len(line) <= size:
                buf += line
                continue
            if buf:
                chunks.append(buf)
                buf = ""
            # Hard-wrap a single line longer than size.
            while len(line) > size:
                chunks.append(line[:size])
                line = line[size:]
            buf = line
        if buf:
            chunks.append(buf)
        return chunks
