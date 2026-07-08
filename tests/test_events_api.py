"""Integration test for the per-user GET /events SSE channel."""

import asyncio
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import AsyncBaseTransport, AsyncByteStream, AsyncClient, Request, Response
from sqlalchemy.ext.asyncio import AsyncEngine

from capybara.api.dependencies import get_current_user, get_event_bus
from capybara.config import Settings
from capybara.db.engine import create_sessionmaker
from capybara.db.models import User
from capybara.main import app
from capybara.services.event_bus import EventBus


class _StreamingASGITransport(AsyncBaseTransport):
    """ASGI transport that delivers response chunks as they arrive.

    httpx's built-in ASGITransport buffers the entire response body before returning,
    which causes test hangs with infinite SSE streams. This transport runs the ASGI app
    in a background asyncio task and streams chunks via a queue, cancelling the task when
    the response stream is closed.
    """

    def __init__(self, asgi_app: object) -> None:
        self._app = asgi_app

    async def handle_async_request(self, request: Request) -> Response:  # type: ignore[override]
        body_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        status_holder: list[int] = []
        raw_headers: list[tuple[bytes, bytes]] = []
        headers_ready = asyncio.Event()
        disconnect_event = asyncio.Event()
        request_complete = False

        async def receive() -> dict:  # type: ignore[type-arg]
            nonlocal request_complete
            if not request_complete:
                request_complete = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await disconnect_event.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict) -> None:  # type: ignore[type-arg]
            if message["type"] == "http.response.start":
                status_holder.append(message["status"])
                raw_headers.extend(message.get("headers", []))
                headers_ready.set()
            elif message["type"] == "http.response.body":
                body: bytes = message.get("body", b"")
                more_body: bool = message.get("more_body", True)
                if body:
                    await body_queue.put(body)
                if not more_body:
                    await body_queue.put(None)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": request.method,
            "headers": [(k.lower(), v) for k, v in request.headers.raw],
            "scheme": request.url.scheme,
            "path": request.url.path,
            "raw_path": request.url.raw_path.split(b"?")[0],
            "query_string": request.url.query,
            "server": (request.url.host, request.url.port or 80),
            "client": ("127.0.0.1", 0),
            "root_path": "",
        }

        app_task = asyncio.create_task(self._app(scope, receive, send))  # type: ignore[operator]
        await headers_ready.wait()

        class _Body(AsyncByteStream):
            async def __aiter__(self) -> AsyncIterator[bytes]:
                while True:
                    chunk = await body_queue.get()
                    if chunk is None:
                        break
                    yield chunk

            async def aclose(self) -> None:
                disconnect_event.set()
                app_task.cancel()
                try:
                    await app_task
                except (asyncio.CancelledError, Exception):
                    pass

        return Response(status_holder[0], headers=raw_headers, stream=_Body())


@pytest_asyncio.fixture
async def bus() -> EventBus:
    return EventBus()


@pytest_asyncio.fixture
async def client(engine: AsyncEngine, settings: Settings, make_user, bus: EventBus):  # type: ignore[no-untyped-def]
    maker = create_sessionmaker(engine)
    async with maker() as setup:
        user = await make_user(setup, username="roman", display_name="Роман")
        await setup.commit()
        user_id = user.id

    async def _override_user():  # type: ignore[no-untyped-def]
        async with maker() as sess:
            fetched = await sess.get(User, user_id)
            assert fetched is not None
            yield fetched

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_event_bus] = lambda: bus
    transport = _StreamingASGITransport(app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.user_id = user_id  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()


async def test_events_endpoint_streams_published_event(client: AsyncClient, bus: EventBus) -> None:
    async with client.stream("GET", "/events") as resp:
        assert resp.status_code == 200

        async def _publish_after_subscribe() -> None:
            await asyncio.sleep(0.1)  # let the endpoint register its subscription
            await bus.publish(
                client.user_id,  # type: ignore[attr-defined]
                {"event": "memory-save", "data": {"message_id": "m1"}},
            )

        task = asyncio.create_task(_publish_after_subscribe())
        received = ""
        async for chunk in resp.aiter_text():
            received += chunk
            if "event: memory-save" in received:
                break
        await task
    assert "event: memory-save" in received
    assert '"message_id": "m1"' in received
