"""Event bus — Redis pubsub in production, in-process asyncio.Queue in tests.

Two-tier model:
- `publish(topic, payload)`: fire-and-forget fanout
- `subscribe(topic, handler)`: async handler invoked for each message

For at-least-once delivery with retries, use Celery tasks as subscribers
(see `infrastructure/celery_app.py` — `process_execution_report`, etc.).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections import defaultdict
from collections.abc import Awaitable, Callable
from platform.core.config import get_settings
from platform.core.logging import get_logger
from typing import Any

import redis.asyncio as aioredis

_log = get_logger(__name__)
Handler = Callable[[dict[str, Any]], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._redis: aioredis.Redis | None = None
        self._pubsub_task: asyncio.Task | None = None
        self._local_only: bool = False

    async def connect(self) -> None:
        settings = get_settings()
        if settings.env == "test":
            self._local_only = True
            return
        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)

        # Retry the initial ping — Redis may still be starting when we come up.
        max_attempts = 5
        for attempt in range(1, max_attempts + 1):
            try:
                await self._redis.ping()
                break
            except Exception as exc:
                if attempt == max_attempts:
                    _log.error(
                        "event_bus_redis_unreachable",
                        url=settings.redis_url,
                        attempts=max_attempts,
                        error=str(exc),
                    )
                    raise
                wait = 2 ** attempt  # 2s, 4s, 8s, 16s
                _log.warning(
                    "event_bus_redis_retry",
                    attempt=attempt,
                    wait_seconds=wait,
                    error=str(exc),
                )
                await asyncio.sleep(wait)

        self._pubsub_task = asyncio.create_task(self._pubsub_loop())
        _log.info("event_bus_connected", url=settings.redis_url)

    async def disconnect(self) -> None:
        if self._pubsub_task:
            self._pubsub_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._pubsub_task
        if self._redis:
            await self._redis.close()

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        body = json.dumps({"topic": topic, "payload": payload}, default=str)
        # Always invoke in-process handlers (low latency for hot path)
        for h in list(self._handlers.get(topic, [])):
            try:
                await h(payload)
            except Exception:
                _log.exception("local_handler_error", topic=topic)
        # Then fan out to other processes via Redis
        if self._redis is not None and not self._local_only:
            await self._redis.publish(topic, body)

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._handlers[topic].append(handler)

    async def _pubsub_loop(self) -> None:
        if self._redis is None:
            return
        topics = list(self._handlers.keys())
        if not topics:
            return
        async with self._redis.pubsub() as pubsub:
            await pubsub.subscribe(*topics)
            _log.info("event_bus_subscribed", topics=topics)
            async for msg in pubsub.listen():
                if msg["type"] != "message":
                    continue
                try:
                    data = json.loads(msg["data"])
                    topic = data["topic"]
                    payload = data["payload"]
                except Exception:
                    _log.warning("bad_pubsub_message", raw=msg["data"][:200])
                    continue
                # Cross-process messages get delivered to local subscribers too
                for h in list(self._handlers.get(topic, [])):
                    try:
                        await h(payload)
                    except Exception:
                        _log.exception("cross_process_handler_error", topic=topic)


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
