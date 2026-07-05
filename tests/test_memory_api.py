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

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_sessionmaker] = lambda: maker
    app.dependency_overrides[get_settings_dep] = lambda: settings
    app.dependency_overrides[get_agent] = lambda: StubMemoryAgent(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


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


async def test_settings_toggle(client: AsyncClient) -> None:
    assert (await client.get("/memory/settings")).json() == {"auto_capture": True}
    patched = await client.patch("/memory/settings", json={"auto_capture": False})
    assert patched.status_code == 200 and patched.json() == {"auto_capture": False}


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
