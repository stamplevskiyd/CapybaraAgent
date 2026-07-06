"""Per-user server push channel: a persistent SSE stream of background events."""

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from capybara.api.dependencies import get_current_user, get_event_bus
from capybara.api.sse import SSE_HEADERS, format_sse
from capybara.db.models import User
from capybara.services.event_bus import EventBus

router = APIRouter(tags=["events"])

#: Idle interval after which a keepalive comment is sent to hold the connection open.
_KEEPALIVE_SECONDS = 15.0


@router.get("/events")
async def events(
    user: Annotated[User, Depends(get_current_user)],
    bus: Annotated[EventBus, Depends(get_event_bus)],
) -> StreamingResponse:
    """Stream this user's background events (e.g. memory-save) as SSE until disconnect."""

    async def event_stream() -> AsyncIterator[str]:
        async with bus.subscribe(user.id) as queue:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SECONDS)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield format_sse(item["event"], item["data"])

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)
