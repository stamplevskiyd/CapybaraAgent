"""In-process per-user pub/sub for pushing server-side events to SSE subscribers.

Process-local by design: this is the single-container stand-in for a shared broker
(Redis pub/sub) that a future horizontal-scaling / background-tasks slice will swap in,
mirroring ``schedule_extraction`` being a stand-in for a real task queue.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


class EventBus:
    """Fan out events to per-user subscriber queues held entirely in memory."""

    def __init__(self, max_queue: int = 100) -> None:
        """Create an empty bus whose subscriber queues hold at most *max_queue* events."""
        self._max_queue = max_queue
        self._subscribers: dict[UUID, set[asyncio.Queue[dict[str, Any]]]] = {}

    async def publish(self, user_id: UUID, event: dict[str, Any]) -> None:
        """Deliver *event* to every active subscriber of *user_id* (best-effort)."""
        for queue in list(self._subscribers.get(user_id, ())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:  # slow consumer — drop rather than block the publisher
                logger.warning("dropping event for user %s: subscriber queue full", user_id)

    @asynccontextmanager
    async def subscribe(self, user_id: UUID) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        """Register a fresh queue for *user_id* and remove it when the context exits."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._max_queue)
        self._subscribers.setdefault(user_id, set()).add(queue)
        try:
            yield queue
        finally:
            subs = self._subscribers.get(user_id)
            if subs is not None:
                subs.discard(queue)
                if not subs:
                    del self._subscribers[user_id]
