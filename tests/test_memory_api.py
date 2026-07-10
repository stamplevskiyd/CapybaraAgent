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

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_sessionmaker] = lambda: maker
    app.dependency_overrides[get_settings_dep] = lambda: settings
    app.dependency_overrides[get_model_registry] = lambda: StubMemoryAgent(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_create_fact_returns_503_when_embedding_model_missing(
    client: AsyncClient, settings: Settings
) -> None:
    """A missing embedding model surfaces an actionable 503, not a generic 500."""
    from capybara.agent.errors import EmbeddingModelUnavailableError

    class NoEmbedAgent(StubMemoryAgent):
        async def embed(self, texts):  # type: ignore[no-untyped-def]
            raise EmbeddingModelUnavailableError(settings.embedding_model)

    app.dependency_overrides[get_model_registry] = lambda: NoEmbedAgent(settings)
    resp = await client.post(
        "/memory/facts", json={"content": "Любит чай", "category": "preference"}
    )
    assert resp.status_code == 503
    assert "ollama pull" in resp.json()["detail"].lower()


async def test_create_fact_returns_502_when_ollama_unreachable(
    client: AsyncClient, settings: Settings
) -> None:
    """A genuine provider outage surfaces a 502, distinct from the fixable-config 503."""
    from capybara.agent.errors import ModelProviderError

    class DownAgent(StubMemoryAgent):
        async def embed(self, texts):  # type: ignore[no-untyped-def]
            raise ModelProviderError(settings.ollama_base_url)

    app.dependency_overrides[get_model_registry] = lambda: DownAgent(settings)
    resp = await client.post("/memory/facts", json={"content": "Любит чай", "category": "personal"})
    assert resp.status_code == 502


async def test_update_fact_returns_503_when_embedding_model_missing(
    client: AsyncClient, settings: Settings
) -> None:
    """The re-embed on a content update also surfaces the actionable 503, not a 500."""
    from capybara.agent.errors import EmbeddingModelUnavailableError

    created = await client.post("/memory/facts", json={"content": "старый", "category": "personal"})
    fact_id = created.json()["id"]

    class NoEmbedAgent(StubMemoryAgent):
        async def embed(self, texts):  # type: ignore[no-untyped-def]
            raise EmbeddingModelUnavailableError(settings.embedding_model)

    app.dependency_overrides[get_model_registry] = lambda: NoEmbedAgent(settings)
    resp = await client.patch(f"/memory/facts/{fact_id}", json={"content": "новый"})
    assert resp.status_code == 503
    assert "ollama pull" in resp.json()["detail"].lower()


async def test_fact_crud_flow(client: AsyncClient) -> None:
    created = await client.post(
        "/memory/facts", json={"content": "Любит чай", "category": "preference"}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["source"] == "manual" and body["category"] == "preference"
    fact_id = body["id"]

    listed = await client.get("/memory/facts")
    assert [f["id"] for f in listed.json()] == [fact_id]

    patched = await client.patch(f"/memory/facts/{fact_id}", json={"content": "Обожает чай"})
    assert patched.status_code == 200 and patched.json()["content"] == "Обожает чай"

    deleted = await client.delete(f"/memory/facts/{fact_id}")
    assert deleted.status_code == 204
    assert (await client.get("/memory/facts")).json() == []


async def test_patch_requires_a_field(client: AsyncClient) -> None:
    created = await client.post("/memory/facts", json={"content": "x", "category": "personal"})
    fact_id = created.json()["id"]
    resp = await client.patch(f"/memory/facts/{fact_id}", json={})
    assert resp.status_code == 422


async def test_facts_are_per_user_isolated(
    client: AsyncClient, engine: AsyncEngine, settings: Settings, make_user
) -> None:  # type: ignore[no-untyped-def]
    from capybara.repositories.fact_repo import FactRepo

    maker = create_sessionmaker(engine)
    async with maker() as s:
        other = await make_user(s, username="other", display_name="Other")
        await FactRepo(s).create(
            user_id=other.id,
            category="personal",
            content="secret",
            embedding=[0.2] * 768,
            source="manual",
        )
        await s.commit()
        async with maker() as s2:
            other_fact = (await FactRepo(s2).list())[0]
            other_fact_id = other_fact.id

    # Current user cannot see it, and cannot mutate it (404, not 403 leak).
    assert (await client.get("/memory/facts")).json() == []
    patch_resp = await client.patch(f"/memory/facts/{other_fact_id}", json={"content": "hax"})
    assert patch_resp.status_code == 404
    assert (await client.delete(f"/memory/facts/{other_fact_id}")).status_code == 404


async def test_update_fact_lost_race_returns_404(client: AsyncClient) -> None:
    """PATCH surfaces 404 when the fact vanishes between the ownership check and the update.

    get_owned_fact reads on the request session while the service re-reads on its own
    sessions; a concurrent delete in that window makes update_fact return None. That
    must map to the same 404 as a missing fact — not an assert that becomes a 500.
    """
    from capybara.api.dependencies import get_memory_service

    created = await client.post(
        "/memory/facts", json={"content": "Любит чай", "category": "preference"}
    )
    fact_id = created.json()["id"]

    class VanishedFactService:
        async def update_fact(self, user_id, fact_id, *, content=None, category=None):  # type: ignore[no-untyped-def]
            return None  # the fact was deleted between the route check and this call

    app.dependency_overrides[get_memory_service] = lambda: VanishedFactService()
    resp = await client.patch(f"/memory/facts/{fact_id}", json={"content": "Новое"})
    assert resp.status_code == 404
