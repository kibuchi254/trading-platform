"""Email notification channel — async SMTP via ``aiosmtplib``.

The dependency is imported lazily inside :meth:`EmailChannel.send` so the
platform can boot without the package installed when email notifications
are not used.
"""

from __future__ import annotations

from email.message import EmailMessage
from platform.core.config import get_settings
from platform.core.logging import get_logger
from platform.notifications.base import NotificationChannel

_log = get_logger(__name__)


class EmailChannel(NotificationChannel):
    """Async SMTP email channel.

    Configuration is sourced from :class:`Settings`:

        - ``smtp_host``     — SMTP server hostname (None disables the channel)
        - ``smtp_port``     — TCP port (587 → STARTTLS, 465 → implicit TLS)
        - ``smtp_user``     — SMTP username (also used as envelope From)
        - ``smtp_password`` — SMTP password (SecretStr)

    HTML detection:
        If ``body`` starts with ``<html>`` or ``<body>`` (case-insensitive,
        leading whitespace tolerated), the message is sent as
        ``multipart/alternative`` with a plain-text fallback and an HTML
        part. Otherwise it is sent as ``text/plain``.

    TLS strategy:
        Port 587 → STARTTLS negotiated after EHLO (default).
        Port 465 → implicit TLS from connection start.
        Other ports → plaintext (e.g. local MailHog on 1025 for dev).

    Returns:
        ``True`` on successful SMTP delivery (server accepted the message),
        ``False`` on any error (connection refused, auth failure, etc.).
    """

    name = "email"

    def __init__(self) -> None:
        settings = get_settings()
        self.host: str | None = settings.smtp_host
        self.port: int = settings.smtp_port
        self.user: str | None = settings.smtp_user
        self.password: str | None = (
            settings.smtp_password.get_secret_value()
            if settings.smtp_password is not None
            else None
        )
        # From address defaults to the SMTP user — most providers require this.
        self.from_addr: str = self.user or "atlas@localhost"

    async def send(self, to: str, subject: str, body: str) -> bool:
        """Send an email.

        Args:
            to: Recipient email address (e.g. ``trader@example.com``).
            subject: Email subject line. Empty string → ``(no subject)``.
            body: Plain text or HTML (auto-detected from leading tag).

        Returns:
            ``True`` on success, ``False`` on failure. All exceptions are
            logged and swallowed — the dispatcher handles retry policy.
        """
        if not self.host:
            _log.error("email_send_no_host", to=to)
            return False

        msg = self._build_message(to, subject, body)

        try:
            import aiosmtplib  # imported lazily — optional dependency
        except ImportError:
            _log.exception("email_aiosmtplib_missing")
            return False

        use_tls = self.port == 465
        use_starttls = self.port == 587
        try:
            await aiosmtplib.send(
                msg,
                hostname=self.host,
                port=self.port,
                username=self.user,
                password=self.password,
                start_tls=use_starttls,
                use_tls=use_tls,
            )
            _log.info("email_sent", to=to, subject=subject, port=self.port)
            return True
        except Exception as exc:
            _log.exception(
                "email_send_failed",
                to=to,
                subject=subject,
                host=self.host,
                port=self.port,
                error=str(exc),
            )
            return False

    # ── Helpers ────────────────────────────────────────────────────────
    def _build_message(self, to: str, subject: str, body: str) -> EmailMessage:
        """Construct an :class:`EmailMessage` with HTML auto-detection."""
        msg = EmailMessage()
        msg["From"] = self.from_addr
        msg["To"] = to
        msg["Subject"] = subject or "(no subject)"

        stripped = body.lstrip().lower()
        if stripped.startswith("<html") or stripped.startswith("<body"):
            # Plain-text fallback for clients that do not render HTML.
            msg.set_content("This message requires an HTML-capable email client.")
            msg.add_alternative(body, subtype="html")
        else:
            msg.set_content(body)
        return msg
