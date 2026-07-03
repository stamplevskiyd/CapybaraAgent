import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from capybara.api.dependencies import get_agent, get_current_user, get_session
from capybara.config import Settings
from capybara.db.models import User
from capybara.main import app
from support import FakeAgent


@pytest_asyncio.fixture
async def client(engine, settings: Settings):  # type: ignore[no-untyped-def]
    from capybara.db.engine import create_sessionmaker

    maker = create_sessionmaker(engine)
    async with maker() as setup:
        user = User(username="roman", display_name="Роман")
        setup.add(user)
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
    chat_id = (await client.post("/chats", json={"title": "c"})).json()["id"]

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
