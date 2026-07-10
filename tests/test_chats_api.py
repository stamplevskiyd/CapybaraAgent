import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from capybara.api.dependencies import (
    get_current_user,
    get_model_registry,
    get_session,
    get_sessionmaker,
    get_settings_dep,
)
from capybara.config import Settings
from capybara.db.engine import create_sessionmaker
from capybara.db.models import Chat, User
from capybara.main import app
from support import FakeAgent


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
    app.dependency_overrides[get_model_registry] = lambda: FakeAgent(settings, "Ответ агента")
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


async def test_create_chat_title_too_long_returns_422(client: AsyncClient) -> None:
    """A title beyond the column bound is rejected before reaching the DB."""
    resp = await client.post("/chats", json={"title": "x" * 201})
    assert resp.status_code == 422


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

    app.dependency_overrides[get_model_registry] = lambda: DownAgent(settings, "x")
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


async def test_delete_chat_removes_it(client: AsyncClient) -> None:
    chat_id = (await client.post("/chats", json={"title": "c", "model": "test-model"})).json()["id"]

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
