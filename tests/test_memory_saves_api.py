"""GET /chats/{id} exposes persisted memory_saves on assistant messages."""

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
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.message_repo import MessageRepo
from support import FakeAgent


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

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_sessionmaker] = lambda: maker
    app.dependency_overrides[get_settings_dep] = lambda: settings
    app.dependency_overrides[get_agent] = lambda: FakeAgent(settings, "Ответ")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.maker = maker  # type: ignore[attr-defined]
        c.user_id = user_id  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()


async def test_get_chat_serializes_memory_saves(client: AsyncClient) -> None:
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]
    saves = [{"content": "Любит чай", "category": "preference"}]
    async with client.maker() as sess:  # type: ignore[attr-defined]
        chat = await ChatRepo(sess).get(chat_id)  # type: ignore[arg-type]
        assert chat is not None
        messages = MessageRepo(sess)
        msg = await messages.create(chat_id=chat.id, role="assistant", content="Здравствуй")
        await messages.update(msg, memory_saves=saves)
        await sess.commit()

    detail = (await client.get(f"/chats/{chat_id}")).json()
    assistant = [m for m in detail["messages"] if m["role"] == "assistant"][-1]
    assert assistant["memory_saves"] == saves
