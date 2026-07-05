"""Integration tests for auto-capture BackgroundTask wired to POST /chats/{id}/messages."""

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
from capybara.db.models import User
from capybara.main import app
from support import StubMemoryAgent


@pytest_asyncio.fixture
async def client(engine: AsyncEngine, settings: Settings, make_user):  # type: ignore[no-untyped-def]
    maker = create_sessionmaker(engine)
    async with maker() as setup:
        user = await make_user(setup, username="roman", display_name="Роман")
        await setup.commit()
        user_id = user.id

    async def _override_session():  # type: ignore[no-untyped-def]
        async with maker() as sess:
            try:
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                raise

    async def _override_user():  # type: ignore[no-untyped-def]
        async with maker() as sess:
            fetched = await sess.get(User, user_id)
            assert fetched is not None
            yield fetched

    agent = StubMemoryAgent(
        settings,
        output_text="Ответ",
        extracted={"facts": [{"content": "Любит чай", "category": "preference"}]},
    )
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_sessionmaker] = lambda: maker
    app.dependency_overrides[get_settings_dep] = lambda: settings
    app.dependency_overrides[get_agent] = lambda: agent
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_send_message_auto_captures_fact(client: AsyncClient) -> None:
    """POST /chats/{id}/messages triggers auto-capture after the stream drains."""
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()[
        "id"
    ]
    async with client.stream(
        "POST", f"/chats/{chat_id}/messages", json={"content": "Привет"}
    ) as resp:
        assert resp.status_code == 200
        async for _ in resp.aiter_text():
            pass

    facts = (await client.get("/memory/facts")).json()
    assert [f["content"] for f in facts] == ["Любит чай"]
    assert facts[0]["source"] == "auto"


async def test_regenerate_does_not_auto_capture(client: AsyncClient) -> None:
    """POST /chats/{id}/messages/regenerate does NOT attach a BackgroundTask."""
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()[
        "id"
    ]
    async with client.stream(
        "POST", f"/chats/{chat_id}/messages", json={"content": "Привет"}
    ) as resp:
        async for _ in resp.aiter_text():
            pass
    # Clear anything captured by the first send so we measure regenerate alone.
    for f in (await client.get("/memory/facts")).json():
        await client.delete(f"/memory/facts/{f['id']}")

    async with client.stream("POST", f"/chats/{chat_id}/messages/regenerate") as resp:
        assert resp.status_code == 200
        async for _ in resp.aiter_text():
            pass

    assert (await client.get("/memory/facts")).json() == []
