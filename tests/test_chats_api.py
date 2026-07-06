import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from capybara.api.dependencies import (
    get_agent,
    get_current_user,
    get_session,
    get_sessionmaker,
    get_settings_dep,
)
from capybara.config import Settings
from capybara.db.engine import create_sessionmaker
from capybara.db.models import Chat, User
from capybara.main import app
from support import (
    EmptyReplyAgent,
    FakeAgent,
    PartialThenFailAgent,  # noqa: F401
    RaisingAgent,
    ScriptedToolAgent,
    SlowStreamAgent,
)


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
    app.dependency_overrides[get_settings_dep] = lambda: settings
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
    # agent.iter() streams token-by-token; reconstruct the full reply from delta frames.
    delta_text = ""
    for frame in body.split("\n\n"):
        if not frame.strip():
            continue
        lines = frame.strip().splitlines()
        if any(line == "event: delta" for line in lines):
            for line in lines:
                if line.startswith("data:"):
                    payload = json.loads(line[5:].strip())
                    delta_text += payload.get("text", "")
    assert delta_text == "Ответ агента"

    fetched = await client.get(f"/chats/{chat_id}")
    roles = [m["role"] for m in fetched.json()["messages"]]
    assert roles == ["user", "assistant"]


async def test_concurrent_sends_to_same_chat_do_not_interleave(
    client: AsyncClient, settings: Settings
) -> None:
    """Two overlapping sends on one chat serialize into clean user/assistant pairs.

    Without a per-chat turn lock the two turns interleave: both user messages land
    before either assistant reply, producing user,user,assistant,assistant.
    """
    import asyncio

    # Slow stream so the two turns genuinely overlap on the event loop.
    app.dependency_overrides[get_agent] = lambda: SlowStreamAgent(settings, "ok")
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]

    r1, r2 = await asyncio.gather(
        client.post(f"/chats/{chat_id}/messages", json={"content": "первый"}),
        client.post(f"/chats/{chat_id}/messages", json={"content": "второй"}),
    )
    assert r1.status_code == 200
    assert r2.status_code == 200

    msgs = (await client.get(f"/chats/{chat_id}")).json()["messages"]
    roles = [m["role"] for m in msgs]
    assert roles == ["user", "assistant", "user", "assistant"], roles


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


async def test_empty_agent_reply_still_emits_done(client: AsyncClient, settings: Settings) -> None:
    """A successful but empty model reply must still terminate the SSE stream."""
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]
    # EmptyReplyAgent is used instead of FakeAgent(settings, "") because TestModel("")
    # raises UnexpectedModelBehavior under agent.iter() (no output → retry exhausted).
    # EmptyReplyAgent yields zero events and returns normally, faithfully simulating
    # a successful-but-empty reply without touching production error handling.
    app.dependency_overrides[get_agent] = lambda: EmptyReplyAgent(settings, "")

    async with client.stream(
        "POST", f"/chats/{chat_id}/messages", json={"content": "Привет"}
    ) as resp:
        assert resp.status_code == 200
        body = ""
        async for chunk in resp.aiter_text():
            body += chunk

    assert "event: done" in body
    assert '"message_id": null' in body
    fetched = await client.get(f"/chats/{chat_id}")
    assert [m["role"] for m in fetched.json()["messages"]] == ["user"]


async def test_create_chat_blank_title_returns_422(client: AsyncClient) -> None:
    """Whitespace-only titles are invalid; omit the field to use the default title."""
    resp = await client.post("/chats", json={"title": "   ", "model": "test-model"})
    assert resp.status_code == 422


async def test_patch_chat_blank_title_returns_422(client: AsyncClient) -> None:
    """Whitespace-only renames are invalid."""
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]
    resp = await client.patch(f"/chats/{chat_id}", json={"title": "   "})
    assert resp.status_code == 422


async def test_patch_chat_blank_model_returns_422(client: AsyncClient) -> None:
    """Whitespace-only model names fail request validation, not provider validation."""
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]
    resp = await client.patch(f"/chats/{chat_id}", json={"model": "   "})
    assert resp.status_code == 422


async def test_send_whitespace_message_returns_422(client: AsyncClient) -> None:
    """Whitespace-only messages are not valid user turns."""
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]
    resp = await client.post(f"/chats/{chat_id}/messages", json={"content": "   "})
    assert resp.status_code == 422


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


# ---------------------------------------------------------------------------
# POST /chats/{chat_id}/messages/regenerate tests
# ---------------------------------------------------------------------------


async def test_regenerate_streams_sse_and_no_duplicate_user_message(
    client: AsyncClient,
) -> None:
    """Regenerate removes the old assistant reply and streams a new one.

    The number of user messages must remain exactly 1 — regenerate must never
    write a second user row.
    """
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]

    # First send creates one user + one assistant
    async with client.stream(
        "POST", f"/chats/{chat_id}/messages", json={"content": "Привет"}
    ) as resp:
        assert resp.status_code == 200
        async for _ in resp.aiter_text():
            pass

    # Regenerate the assistant reply
    async with client.stream("POST", f"/chats/{chat_id}/messages/regenerate") as resp:
        assert resp.status_code == 200
        body = ""
        async for chunk in resp.aiter_text():
            body += chunk

    assert "event: delta" in body
    assert "event: done" in body

    fetched = await client.get(f"/chats/{chat_id}")
    messages = fetched.json()["messages"]
    user_msgs = [m for m in messages if m["role"] == "user"]
    assistant_msgs = [m for m in messages if m["role"] == "assistant"]
    assert len(user_msgs) == 1, "regenerate must not create a duplicate user message"
    assert len(assistant_msgs) == 1


async def test_regenerate_sse_headers_match_send_message(
    client: AsyncClient,
) -> None:
    """Regenerate endpoint must include the same SSE no-buffer headers as send_message."""
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]
    await client.post(f"/chats/{chat_id}/messages", json={"content": "Привет"})

    async with client.stream("POST", f"/chats/{chat_id}/messages/regenerate") as resp:
        assert resp.status_code == 200
        async for _ in resp.aiter_text():
            pass

    assert resp.headers.get("cache-control") == "no-cache"
    assert resp.headers.get("x-accel-buffering") == "no"
    assert resp.headers.get("connection") == "keep-alive"


async def test_regenerate_no_trailing_assistant_still_streams(
    client: AsyncClient,
    engine: AsyncEngine,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """Regenerate works even when the last user message has no assistant reply yet."""
    from capybara.db.models import Message

    maker = create_sessionmaker(engine)

    # Create a chat via API to get a valid chat_id owned by the client user
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]

    # Insert a user message directly without an assistant message
    import uuid

    async with maker() as setup:
        setup.add(Message(chat_id=uuid.UUID(chat_id), role="user", content="Bare question"))
        await setup.commit()

    async with client.stream("POST", f"/chats/{chat_id}/messages/regenerate") as resp:
        assert resp.status_code == 200
        body = ""
        async for chunk in resp.aiter_text():
            body += chunk

    assert "event: delta" in body
    assert "event: done" in body

    fetched = await client.get(f"/chats/{chat_id}")
    messages = fetched.json()["messages"]
    user_msgs = [m for m in messages if m["role"] == "user"]
    assert len(user_msgs) == 1


async def test_regenerate_no_user_message_returns_409(client: AsyncClient) -> None:
    """Regenerate on a chat with no user messages returns 409 Conflict."""
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]
    resp = await client.post(f"/chats/{chat_id}/messages/regenerate")
    assert resp.status_code == 409
    assert "regenerate" in resp.json()["detail"].lower()


async def test_regenerate_missing_chat_returns_404(client: AsyncClient) -> None:
    """Regenerate on a non-existent chat returns 404."""
    resp = await client.post("/chats/00000000-0000-0000-0000-000000000099/messages/regenerate")
    assert resp.status_code == 404


async def test_regenerate_other_users_chat_returns_404(
    client: AsyncClient,
    engine: AsyncEngine,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """Regenerate on another user's chat returns 404."""
    from capybara.db.models import Chat as ChatModel

    maker = create_sessionmaker(engine)
    async with maker() as sess:
        other_user = await make_user(sess, username="regen_other", display_name="Other")
        other_chat = ChatModel(user_id=other_user.id, title="private", model="test-model")
        sess.add(other_chat)
        await sess.commit()
        other_chat_id = other_chat.id

    resp = await client.post(f"/chats/{other_chat_id}/messages/regenerate")
    assert resp.status_code == 404


async def test_regenerate_without_model_returns_409(client: AsyncClient) -> None:
    """Regenerate on a chat with no model set returns 409 before any SSE bytes."""
    chat_id = (await client.post("/chats", json={"title": "c"})).json()["id"]  # no model
    resp = await client.post(f"/chats/{chat_id}/messages/regenerate")
    assert resp.status_code == 409


async def test_patch_chat_rename_only(client: AsyncClient) -> None:
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]
    resp = await client.patch(f"/chats/{chat_id}", json={"title": "Переименовано"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Переименовано"
    assert resp.json()["model"] == "test-model"  # untouched


async def test_patch_chat_favorite_only(client: AsyncClient) -> None:
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]
    resp = await client.patch(f"/chats/{chat_id}", json={"is_favorite": True})
    assert resp.status_code == 200
    assert resp.json()["is_favorite"] is True


async def test_patch_chat_empty_body_422(client: AsyncClient) -> None:
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]
    resp = await client.patch(f"/chats/{chat_id}", json={})
    assert resp.status_code == 422


async def test_patch_chat_model_still_validates(client: AsyncClient) -> None:
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]
    ok = await client.patch(f"/chats/{chat_id}", json={"model": "test-model"})
    assert ok.status_code == 200
    bad = await client.patch(f"/chats/{chat_id}", json={"model": "ghost:1b"})
    assert bad.status_code == 409


async def test_delete_chat_removes_it_and_messages(client: AsyncClient) -> None:
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]
    # produce a message so the cascade has something to remove
    async with client.stream("POST", f"/chats/{chat_id}/messages", json={"content": "Привет"}) as r:
        async for _ in r.aiter_text():
            pass

    resp = await client.delete(f"/chats/{chat_id}")
    assert resp.status_code == 204

    gone = await client.get(f"/chats/{chat_id}")
    assert gone.status_code == 404
    listed = await client.get("/chats")
    assert all(c["id"] != chat_id for c in listed.json())


async def test_delete_other_users_chat_404(
    client: AsyncClient,
    engine,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    from capybara.db.engine import create_sessionmaker
    from capybara.db.models import Chat

    maker = create_sessionmaker(engine)
    async with maker() as sess:
        other = await make_user(sess, username="delother", display_name="O")
        chat = Chat(user_id=other.id, title="private", model="test-model")
        sess.add(chat)
        await sess.commit()
        other_chat_id = chat.id

    resp = await client.delete(f"/chats/{other_chat_id}")
    assert resp.status_code == 404


def _sse_events(body: str) -> list[str]:
    return [ln[len("event: ") :] for ln in body.splitlines() if ln.startswith("event: ")]


async def test_first_message_emits_title_event(client: AsyncClient) -> None:
    """The first turn of a default-titled chat emits an SSE title event; later turns do not."""
    chat_id = (await client.post("/chats", json={"model": "test-model"})).json()[
        "id"
    ]  # default title

    async with client.stream("POST", f"/chats/{chat_id}/messages", json={"content": "Привет"}) as r:
        first = "".join([c async for c in r.aiter_text()])
    assert "title" in _sse_events(first)
    assert "event: title" in first

    # Second turn: title already set → no title event.
    async with client.stream("POST", f"/chats/{chat_id}/messages", json={"content": "Ещё"}) as r:
        second = "".join([c async for c in r.aiter_text()])
    assert "title" not in _sse_events(second)


async def test_send_message_streams_tool_call_frames(
    client: AsyncClient, settings: Settings
) -> None:
    """tool-call and tool-result SSE frames are emitted when the agent calls a tool."""
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]
    app.dependency_overrides[get_agent] = lambda: ScriptedToolAgent(settings, "Ответ")
    try:
        async with client.stream(
            "POST", f"/chats/{chat_id}/messages", json={"content": "Что?"}
        ) as resp:
            body = ""
            async for chunk in resp.aiter_text():
                body += chunk
    finally:
        app.dependency_overrides.clear()

    assert "event: tool-call" in body
    assert "event: tool-result" in body
    assert '"name": "recall"' in body
    assert "event: delta" in body


async def _post_message_disconnected(chat_id: str, *, spec_version: str, send) -> None:  # type: ignore[no-untyped-def]
    """POST a message to *chat_id* via a raw ASGI call from an already-disconnected client.

    The receive channel yields the JSON body and then only http.disconnect frames;
    *send* controls how the transport reacts to response bytes (silently discard for
    the pre-2.4 task-group path, raise OSError for the ASGI >= 2.4 path).
    """
    body = json.dumps({"content": "Привет"}).encode()
    messages = iter(
        [
            {"type": "http.request", "body": body, "more_body": False},
            {"type": "http.disconnect"},
        ]
    )

    async def receive():  # type: ignore[no-untyped-def]
        return next(messages, {"type": "http.disconnect"})

    path = f"/chats/{chat_id}/messages"
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": spec_version},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"test"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
    }
    await app(scope, receive, send)


async def test_send_message_releases_turn_lock_on_disconnect_before_streaming(
    client: AsyncClient,
) -> None:
    """Task-group path (ASGI < 2.4): an early disconnect must not leak the turn lock.

    Starlette cancels the streaming task, but anyio only delivers cancellation to tasks
    that have started, so the body generator always begins and its finally releases the
    lock. Pinned so a change in that scheduling behaviour surfaces as a leak here.
    """
    from uuid import UUID

    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]

    async def send(message):  # type: ignore[no-untyped-def]
        pass

    await _post_message_disconnected(chat_id, spec_version="2.0", send=send)

    locks = app.state.chat_turn_locks
    assert not locks.lock_for(UUID(chat_id)).locked()


async def test_send_message_releases_turn_lock_when_send_raises_before_streaming(
    client: AsyncClient,
) -> None:
    """ASGI >= 2.4 path: send() raising on a dead client must not leak the turn lock.

    Here Starlette calls stream_response directly; the OSError from sending the response
    headers surfaces as ClientDisconnect *before the body generator is ever started*, so
    no finally inside it can run and the background task is skipped too. The response
    object itself must guarantee the release, or the chat deadlocks forever.
    """
    from uuid import UUID

    from starlette.requests import ClientDisconnect

    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]

    async def send(message):  # type: ignore[no-untyped-def]
        raise OSError("client disconnected")

    with pytest.raises(ClientDisconnect):
        await _post_message_disconnected(chat_id, spec_version="2.4", send=send)

    locks = app.state.chat_turn_locks
    assert not locks.lock_for(UUID(chat_id)).locked()
