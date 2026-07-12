"""API tests for the /chat-prefs router."""

from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from capybara.api.dependencies import get_current_user, get_session, get_sessionmaker
from capybara.config import Settings
from capybara.db.engine import create_sessionmaker
from capybara.db.models import User
from capybara.main import app

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def prefs_client(engine: AsyncEngine, settings: Settings, make_user):  # type: ignore[no-untyped-def]
    """Authenticated AsyncClient with the chat-prefs router wired to the test database."""
    maker = create_sessionmaker(engine)
    async with maker() as setup:
        user = await make_user(setup, username="prefs_user", display_name="Prefs User")
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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def test_chat_prefs_upsert_list_and_delete(prefs_client: AsyncClient) -> None:
    """A pref can be set, listed, replaced, and deleted through the API."""
    thread_id = str(uuid4())

    # Empty to start.
    assert (await prefs_client.get("/chat-prefs")).json() == []

    # Create.
    created = await prefs_client.put(
        f"/chat-prefs/{thread_id}", json={"is_favorite": True, "model": "llama3.1"}
    )
    assert created.status_code == 200
    assert created.json() == {"thread_id": thread_id, "is_favorite": True, "model": "llama3.1", "mode": "fast"}

    # Listed.
    listed = (await prefs_client.get("/chat-prefs")).json()
    assert listed == [{"thread_id": thread_id, "is_favorite": True, "model": "llama3.1", "mode": "fast"}]

    # Replace (unfavorite, clear model).
    replaced = await prefs_client.put(
        f"/chat-prefs/{thread_id}", json={"is_favorite": False, "model": None}
    )
    assert replaced.json() == {"thread_id": thread_id, "is_favorite": False, "model": None, "mode": "fast"}

    # Delete.
    assert (await prefs_client.delete(f"/chat-prefs/{thread_id}")).status_code == 204
    assert (await prefs_client.get("/chat-prefs")).json() == []
