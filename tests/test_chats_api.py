import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from capybara.api.dependencies import (
    get_agent,
    get_current_user,
    get_session,
    get_sessionmaker,
)
from capybara.config import Settings
from capybara.db.engine import create_sessionmaker
from capybara.db.models import Chat, User
from capybara.main import app
from support import FakeAgent, PartialThenFailAgent, RaisingAgent  # noqa: F401


@pytest_asyncio.fixture
async def client(engine, settings: Settings, make_user):  # type: ignore[no-untyped-def]
    from capybara.db.engine import create_sessionmaker

    maker = create_sessionmaker(engine)
    async with maker() as setup:
        user = await make_user(setup, username="roman", display_name="Роман")
        await setup.commit()
        user_id = user.id

    async def _override_session():  # type: ignore[return]
        async with maker() as sess:
            try:
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                raise

    async def _override_user():  # type: ignore[return]
        async with maker() as sess:
            fetched = await sess.get(User, user_id)
            assert fetched is not None
            yield fetched

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_sessionmaker] = lambda: maker
    app.dependency_overrides[get_agent] = lambda: FakeAgent(settings, "Ответ агента")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_create_and_get_chat(client: AsyncClient) -> None:
    created = await client.post("/chats", json={"title": "Продажи"})
    assert created.status_code == 201
    chat_id = created.json()["id"]

    listed = await client.get("/chats")
    assert any(c["id"] == chat_id for c in listed.json())

    fetched = await client.get(f"/chats/{chat_id}")
    assert fetched.status_code == 200
    assert fetched.json()["messages"] == []


async def test_get_missing_chat_404(client: AsyncClient) -> None:
    resp = await client.get("/chats/00000000-0000-0000-0000-0000000000ff")
    assert resp.status_code == 404


async def test_post_message_missing_chat_404(client: AsyncClient) -> None:
    resp = await client.post(
        "/chats/00000000-0000-0000-0000-000000000099/messages",
        json={"content": "hello"},
    )
    assert resp.status_code == 404


async def test_send_message_streams_sse_and_persists(client: AsyncClient) -> None:
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]

    async with client.stream(
        "POST", f"/chats/{chat_id}/messages", json={"content": "Привет"}
    ) as resp:
        assert resp.status_code == 200
        body = ""
        async for chunk in resp.aiter_text():
            body += chunk
    assert "event: delta" in body
    assert "event: done" in body
    assert "Ответ агента" in body

    fetched = await client.get(f"/chats/{chat_id}")
    roles = [m["role"] for m in fetched.json()["messages"]]
    assert roles == ["user", "assistant"]


async def test_chat_stream_has_sse_no_buffer_headers(client: AsyncClient) -> None:
    """SSE streaming endpoint must include flush-friendly headers.

    Without Cache-Control: no-cache the Vite dev proxy and browser fetch do not
    know the response is a live stream; chunks may be buffered until the
    connection closes, causing assistant messages to never appear in the UI.
    Without X-Accel-Buffering: no nginx would buffer the upstream response in
    production before forwarding it to the client.
    """
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]

    async with client.stream(
        "POST", f"/chats/{chat_id}/messages", json={"content": "Привет"}
    ) as resp:
        assert resp.status_code == 200
        # Drain the stream so the connection closes cleanly.
        async for _ in resp.aiter_text():
            pass

    assert resp.headers.get("cache-control") == "no-cache", (
        "Cache-Control: no-cache is required so browsers and the Vite dev proxy "
        "deliver SSE chunks immediately rather than buffering them"
    )
    assert resp.headers.get("x-accel-buffering") == "no", (
        "X-Accel-Buffering: no is required so nginx does not buffer the upstream "
        "streaming response in production"
    )
    assert resp.headers.get("connection") == "keep-alive", (
        "Connection: keep-alive is required to keep the SSE connection open"
    )


async def test_create_chat_title_too_long_returns_422(client: AsyncClient) -> None:
    """A title beyond the column bound is rejected before reaching the DB."""
    resp = await client.post("/chats", json={"title": "x" * 201})
    assert resp.status_code == 422


async def test_send_empty_message_returns_422(client: AsyncClient) -> None:
    """Empty message content is rejected by request validation."""
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]
    resp = await client.post(f"/chats/{chat_id}/messages", json={"content": ""})
    assert resp.status_code == 422


async def test_send_message_stream_error_is_generic(
    client: AsyncClient, settings: Settings
) -> None:
    """A failure mid-stream surfaces a generic SSE error, never the exception detail."""
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]
    secret = "SECRET-LEAK-should-not-appear-42"
    app.dependency_overrides[get_agent] = lambda: RaisingAgent(settings, secret)

    async with client.stream(
        "POST", f"/chats/{chat_id}/messages", json={"content": "Привет"}
    ) as resp:
        assert resp.status_code == 200
        body = ""
        async for chunk in resp.aiter_text():
            body += chunk

    assert "event: error" in body
    assert secret not in body
    assert "Internal server error" in body


async def test_get_chat_owned_by_other_user_returns_404(
    client: AsyncClient,
    engine: AsyncEngine,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """GET /chats/{id} returns 404 when the chat belongs to a different user."""
    maker = create_sessionmaker(engine)
    async with maker() as sess:
        other_user = await make_user(sess, username="other", display_name="Other")
        other_chat = Chat(user_id=other_user.id, title="private")
        sess.add(other_chat)
        await sess.commit()
        other_chat_id = other_chat.id

    resp = await client.get(f"/chats/{other_chat_id}")
    assert resp.status_code == 404


async def test_send_message_to_other_users_chat_returns_404(
    client: AsyncClient,
    engine: AsyncEngine,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """POST /chats/{id}/messages returns 404 when the chat belongs to a different user."""
    maker = create_sessionmaker(engine)
    async with maker() as sess:
        other_user = await make_user(sess, username="other2", display_name="Other2")
        other_chat = Chat(user_id=other_user.id, title="private2")
        sess.add(other_chat)
        await sess.commit()
        other_chat_id = other_chat.id

    resp = await client.post(f"/chats/{other_chat_id}/messages", json={"content": "hello"})
    assert resp.status_code == 404


async def test_list_models_returns_provider_list(client: AsyncClient) -> None:
    resp = await client.get("/models")
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "ollama"
    assert body["models"] == ["test-model"]


async def test_list_models_502_when_provider_unreachable(
    client: AsyncClient, settings: Settings
) -> None:
    from capybara.agent import ModelProviderError

    class DownAgent(FakeAgent):
        async def list_models(self) -> list[str]:
            raise ModelProviderError(settings.ollama_base_url)

    app.dependency_overrides[get_agent] = lambda: DownAgent(settings, "x")
    resp = await client.get("/models")
    assert resp.status_code == 502
    assert "unreachable" in resp.json()["detail"].lower()


async def test_patch_chat_model_sets_and_validates(client: AsyncClient) -> None:
    chat_id = (await client.post("/chats", json={"title": "c"})).json()["id"]

    ok = await client.patch(f"/chats/{chat_id}", json={"model": "test-model"})
    assert ok.status_code == 200
    assert ok.json()["model"] == "test-model"

    bad = await client.patch(f"/chats/{chat_id}", json={"model": "ghost:1b"})
    assert bad.status_code == 409


async def test_create_chat_with_unknown_model_409(client: AsyncClient) -> None:
    resp = await client.post("/chats", json={"title": "c", "model": "ghost:1b"})
    assert resp.status_code == 409


async def test_send_without_model_returns_409(client: AsyncClient) -> None:
    """A chat with no model selected is rejected up front, not via an SSE error."""
    chat_id = (await client.post("/chats", json={"title": "c"})).json()["id"]  # no model
    resp = await client.post(f"/chats/{chat_id}/messages", json={"content": "Привет"})
    assert resp.status_code == 409
    assert "available" in resp.json()["detail"].lower()
