"""Notification subsystem — base types, dispatcher, and singleton factory.

The dispatcher is the single entry point for all outbound notifications in
ATLAS. It routes :class:`NotificationMessage` instances to the appropriate
channel implementation (email, Telegram, Discord, webhook, ...) and persists
the delivery outcome to the ``notifications`` table.

Channels are pluggable — register any subclass of :class:`NotificationChannel`
via the dispatcher constructor or :meth:`NotificationDispatcher.register`.

Retries use exponential backoff (1s, 5s, 30s) so transient SMTP / API
failures do not cause permanent message loss. The schedule is interpreted as
one initial attempt followed by up to three retries (4 total attempts),
sleeping the corresponding backoff before each retry.

At-least-once delivery semantics apply — idempotency is the responsibility of
downstream consumers (use ``NotificationMessage.meta["idempotency_key"]``).
"""
from __future__ import annotations

import abc
import asyncio
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from platform.core.logging import get_logger
from platform.db.models import Notification
from platform.db.session import db_context
from platform.events.bus import get_event_bus
from platform.events.topics import Topic

_log = get_logger(__name__)

# Delivery priorities — order is informational; channels decide how to react.
Priority = Literal["LOW", "NORMAL", "HIGH", "CRITICAL"]

# Exponential backoff schedule for retries. The initial attempt is immediate;
# subsequent retries sleep for each value in turn (1s → 5s → 30s).
_RETRY_BACKOFF_SECONDS: tuple[int, ...] = (1, 5, 30)


class NotificationChannel(abc.ABC):
    """Abstract base for all notification channels.

    Every channel exposes a uniform ``send`` interface so that the
    :class:`NotificationDispatcher` can route messages polymorphically.
    Concrete channels are responsible for transport-level concerns
    (SMTP, HTTP, etc.) and must return ``True`` on confirmed delivery
    or ``False`` on any failure (after exhausting their own internal
    retries if any).
    """

    name: str = "abstract"

    @abc.abstractmethod
    async def send(self, to: str, subject: str, body: str) -> bool:
        """Deliver a message.

        Args:
            to: Recipient identifier — email address, chat_id, webhook URL,
                etc. Channel-specific semantics apply.
            subject: Short subject / title. May be ignored by channels that
                do not support titles (e.g. plain Telegram messages — used
                as a prefix instead).
            body: Message body. Plain text unless the channel detects a
                structured payload (e.g. HTML for email).

        Returns:
            ``True`` on confirmed delivery, ``False`` otherwise.
        """
        ...


class NotificationMessage(BaseModel):
    """Transport-agnostic notification envelope.

    Attributes:
        channel: Target channel name — must match a registered channel.
        to: Recipient identifier (channel-specific — email, chat_id, URL).
        subject: Optional subject / title.
        body: Message body (plain text or HTML for email).
        meta: Free-form metadata bag — ``org_id``, ``user_id``,
            ``idempotency_key``, ``channel_targets``, etc. are read by the
            dispatcher for persistence and fan-out routing.
        priority: Delivery priority. Higher priorities may bypass quiet
            hours or trigger paging (handled by the dispatcher / channel
            policies).
    """

    channel: str
    to: str
    subject: str | None = None
    body: str
    meta: dict[str, Any] = Field(default_factory=dict)
    priority: Priority = "NORMAL"


class NotificationDispatcher:
    """Routes :class:`NotificationMessage` to channels with retries & persistence.

    Lifecycle:
        1. Construct (or fetch via :func:`get_dispatcher`) — registers the
           default channel set based on populated settings.
        2. Call :meth:`subscribe_to_bus` once at app startup to wire
           ``Topic.NOTIFICATIONS`` events into :meth:`dispatch`.
        3. Any module may publish to ``Topic.NOTIFICATIONS`` with a payload
           matching :class:`NotificationMessage` — the dispatcher handles
           the rest.

    Persistence:
        Every dispatched message is recorded in the ``notifications`` table
        with ``status`` of ``sent`` or ``failed``. The ``meta`` dict may
        carry ``org_id`` and ``user_id`` to populate the FK columns; if
        absent the columns are left NULL (system-originated messages).
    """

    def __init__(self, channels: dict[str, NotificationChannel] | None = None) -> None:
        self._channels: dict[str, NotificationChannel] = dict(channels or {})
        _log.info("dispatcher_initialized", channels=list(self._channels))

    # ── Registration ────────────────────────────────────────────────────
    def register(self, channel: NotificationChannel) -> None:
        """Register or replace a channel by its ``name``."""
        self._channels[channel.name] = channel
        _log.info("channel_registered", channel=channel.name)

    @property
    def channels(self) -> dict[str, NotificationChannel]:
        """Read-only snapshot of registered channels."""
        return dict(self._channels)

    # ── Routing ─────────────────────────────────────────────────────────
    async def dispatch(self, message: NotificationMessage) -> bool:
        """Route a message to its channel with retries + persistence.

        The dispatcher makes an initial attempt immediately, then up to
        three retries with exponential backoff (1s, 5s, 30s). Each retry
        is preceded by the corresponding sleep. Failures are persisted
        with the last error string (truncated to 500 chars to fit the
        schema).

        Args:
            message: Fully populated :class:`NotificationMessage`.

        Returns:
            ``True`` if the channel confirmed delivery, ``False`` otherwise.
        """
        channel = self._channels.get(message.channel)
        if channel is None:
            err = f"unknown_channel:{message.channel}"
            _log.error("dispatch_unknown_channel", channel=message.channel)
            await self._persist(message, success=False, error=err)
            return False

        last_error: str = ""
        # Initial attempt (0s) + one sleep per listed backoff = up to 4 tries.
        for attempt_idx, backoff in enumerate((0, *_RETRY_BACKOFF_SECONDS)):
            if backoff > 0:
                await asyncio.sleep(backoff)
            attempt_num = attempt_idx + 1
            try:
                ok = await channel.send(
                    message.to,
                    message.subject or "",
                    message.body,
                )
            except Exception as exc:  # noqa: BLE001 — log & retry
                last_error = f"{type(exc).__name__}:{exc}"
                _log.warning(
                    "dispatch_attempt_failed",
                    channel=message.channel,
                    attempt=attempt_num,
                    error=last_error,
                )
                continue

            if ok:
                await self._persist(message, success=True)
                _log.info(
                    "dispatch_ok",
                    channel=message.channel,
                    to=message.to,
                    attempt=attempt_num,
                    priority=message.priority,
                )
                return True

            last_error = "channel_returned_false"
            _log.warning(
                "dispatch_attempt_failed",
                channel=message.channel,
                attempt=attempt_num,
                error=last_error,
            )

        await self._persist(message, success=False, error=last_error[:500])
        _log.error(
            "dispatch_failed",
            channel=message.channel,
            to=message.to,
            error=last_error,
        )
        return False

    async def dispatch_to_all(
        self,
        subject: str,
        body: str,
        **kwargs: Any,
    ) -> dict[str, bool]:
        """Fan-out a single subject/body pair to every registered channel.

        Keyword arguments are forwarded to each :class:`NotificationMessage`:

            - ``priority`` (default ``"NORMAL"``) — sets the priority field
            - ``meta`` (default ``{}``) — merged into each message
            - ``meta["channel_targets"]`` — optional ``{channel_name: to}``
              map so each channel receives a different recipient. If a
              channel is absent from the map, ``to`` defaults to empty
              string (the channel decides what to do — Discord ignores it,
              email will fail with no recipient, etc.).

        Args:
            subject: Subject / title for every channel.
            body: Message body.
            **kwargs: ``priority``, ``meta`` (see above).

        Returns:
            Mapping of ``channel_name -> success_bool``. One channel
            failing never aborts the fan-out.
        """
        meta: dict[str, Any] = dict(kwargs.pop("meta", {}))
        priority: Priority = kwargs.pop("priority", "NORMAL")
        targets: dict[str, str] = meta.pop("channel_targets", {})

        results: dict[str, bool] = {}
        for name in self._channels:
            to = targets.get(name, "")
            msg = NotificationMessage(
                channel=name,
                to=to,
                subject=subject,
                body=body,
                meta=dict(meta),
                priority=priority,
            )
            try:
                results[name] = await self.dispatch(msg)
            except Exception:  # noqa: BLE001 — one channel must not abort fan-out
                _log.exception("dispatch_to_all_channel_error", channel=name)
                results[name] = False
        return results

    # ── Event bus integration ──────────────────────────────────────────
    def subscribe_to_bus(self) -> None:
        """Subscribe the dispatcher to ``Topic.NOTIFICATIONS``.

        The event payload is expected to be a dict matching
        :class:`NotificationMessage`. Unknown / malformed payloads are
        logged and dropped (never re-raised) so the bus subscriber loop
        cannot crash. Likewise, any exception during dispatch is logged
        and swallowed.
        """

        async def _handler(payload: dict[str, Any]) -> None:
            try:
                msg = NotificationMessage(**payload)
            except Exception:  # noqa: BLE001
                _log.exception("bus_payload_invalid", payload=payload)
                return
            try:
                await self.dispatch(msg)
            except Exception:  # noqa: BLE001
                _log.exception("bus_dispatch_error", channel=msg.channel)

        get_event_bus().subscribe(Topic.NOTIFICATIONS, _handler)
        _log.info("dispatcher_subscribed_to_bus", topic=Topic.NOTIFICATIONS)

    # ── Persistence ────────────────────────────────────────────────────
    async def _persist(
        self,
        message: NotificationMessage,
        *,
        success: bool,
        error: str | None = None,
    ) -> None:
        """Record the delivery outcome to the ``notifications`` table.

        Failures here must not mask the dispatch result — they are logged
        and swallowed. ``org_id`` and ``user_id`` are read from
        ``message.meta`` if present (cast to UUID).
        """
        org_id = message.meta.get("org_id")
        user_id = message.meta.get("user_id")
        try:
            async with db_context() as session:
                row = Notification(
                    org_id=UUID(str(org_id)) if org_id else None,
                    user_id=UUID(str(user_id)) if user_id else None,
                    channel=message.channel,
                    subject=message.subject,
                    body=message.body,
                    status="sent" if success else "failed",
                    sent_at=datetime.now(timezone.utc) if success else None,
                    error=error,
                )
                session.add(row)
                await session.commit()
        except Exception:  # noqa: BLE001 — persistence is best-effort
            _log.exception(
                "persist_failed",
                channel=message.channel,
                status="sent" if success else "failed",
            )


_dispatcher: NotificationDispatcher | None = None


def get_dispatcher() -> NotificationDispatcher:
    """Singleton factory — auto-registers channels based on settings.

    Channels are only registered if their corresponding settings are
    populated (e.g. ``smtp_host`` for email, ``telegram_bot_token`` for
    Telegram, ``discord_webhook_url`` for Discord). This lets the same
    code run in dev (no channels configured → fan-out is a no-op) and
    production (all channels wired up).

    Returns:
        The process-wide :class:`NotificationDispatcher` instance.
    """
    global _dispatcher
    if _dispatcher is not None:
        return _dispatcher

    # Imports are deferred to avoid a circular import at module load time
    # (channels → base → channels).
    from platform.core.config import get_settings
    from platform.notifications.channels.discord import DiscordChannel
    from platform.notifications.channels.email import EmailChannel
    from platform.notifications.channels.telegram import TelegramChannel

    settings = get_settings()
    channels: dict[str, NotificationChannel] = {}

    if settings.smtp_host:
        try:
            channels["email"] = EmailChannel()
        except Exception:  # noqa: BLE001
            _log.exception("email_channel_init_failed")

    if settings.telegram_bot_token:
        try:
            channels["telegram"] = TelegramChannel()
        except Exception:  # noqa: BLE001
            _log.exception("telegram_channel_init_failed")

    if settings.discord_webhook_url:
        try:
            channels["discord"] = DiscordChannel()
        except Exception:  # noqa: BLE001
            _log.exception("discord_channel_init_failed")

    _dispatcher = NotificationDispatcher(channels)
    return _dispatcher
