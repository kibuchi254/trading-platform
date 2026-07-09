"""Test the NotificationDispatcher with a fake channel + retry logic."""

from __future__ import annotations

from platform.notifications.base import (
    NotificationChannel,
    NotificationDispatcher,
    NotificationMessage,
)


class FakeChannel(NotificationChannel):
    name = "fake"

    def __init__(self, fail_times: int = 0):
        self.fail_times = fail_times
        self.attempts = 0
        self.sent: list[tuple[str, str, str]] = []

    async def send(self, to: str, subject: str, body: str) -> bool:
        self.attempts += 1
        if self.attempts <= self.fail_times:
            return False
        self.sent.append((to, subject, body))
        return True


async def test_dispatch_to_fake_channel_succeeds() -> None:
    dispatcher = NotificationDispatcher()
    channel = FakeChannel()
    dispatcher._channels["fake"] = channel
    msg = NotificationMessage(channel="fake", to="user@example.com", subject="Hi", body="Hello")
    result = await dispatcher.dispatch(msg)
    assert result is True
    assert len(channel.sent) == 1


async def test_dispatch_retries_on_failure() -> None:
    dispatcher = NotificationDispatcher()
    dispatcher._retry_attempts = 3
    dispatcher._retry_backoff = [0.01, 0.01, 0.01]  # fast for tests
    channel = FakeChannel(fail_times=2)  # succeeds on 3rd attempt
    dispatcher._channels["fake"] = channel
    msg = NotificationMessage(channel="fake", to="user@example.com", subject="Hi", body="Hello")
    result = await dispatcher.dispatch(msg)
    assert result is True
    assert channel.attempts == 3
    assert len(channel.sent) == 1


async def test_dispatch_fails_after_max_retries() -> None:
    dispatcher = NotificationDispatcher()
    dispatcher._retry_attempts = 2
    dispatcher._retry_backoff = [0.01, 0.01]
    channel = FakeChannel(fail_times=99)  # always fails
    dispatcher._channels["fake"] = channel
    msg = NotificationMessage(channel="fake", to="user@example.com", subject="Hi", body="Hello")
    result = await dispatcher.dispatch(msg)
    assert result is False
    assert channel.attempts == 3  # initial + 2 retries


async def test_dispatch_to_all_fans_out() -> None:
    dispatcher = NotificationDispatcher()
    ch1 = FakeChannel()
    ch2 = FakeChannel()
    dispatcher._channels["fake1"] = ch1
    dispatcher._channels["fake2"] = ch2
    await dispatcher.dispatch_to_all(subject="Alert", body="Risk breach")
    assert len(ch1.sent) == 1
    assert len(ch2.sent) == 1


async def test_dispatch_unknown_channel_returns_false() -> None:
    dispatcher = NotificationDispatcher()
    msg = NotificationMessage(channel="nonexistent", to="x", subject="y", body="z")
    result = await dispatcher.dispatch(msg)
    assert result is False
