"""Integration tests for the POST /auth/login endpoint and JWT-based auth."""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from capybara.api.dependencies import get_session
from capybara.config import Settings
from capybara.db.engine import create_sessionmaker
from capybara.db.models import User
from capybara.main import app
from capybara.security.tokens import decode_access_token


@pytest_asyncio.fixture
async def client(engine, settings: Settings, make_user):  # type: ignore[no-untyped-def]
    """AsyncClient with a seeded user and real JWT auth (no get_current_user override)."""
    maker = create_sessionmaker(engine)
    async with maker() as setup:
        await make_user(setup, username="roman", display_name="Роман", password="password123")
        await setup.commit()

    async def _override_session():  # type: ignore[return]
        async with maker() as sess:
            try:
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                raise

    app.state.settings = settings
    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    del app.state.settings
    async with maker() as cleanup:
        for row in (await cleanup.execute(select(User))).scalars().all():
            await cleanup.delete(row)
        await cleanup.commit()


async def test_login_success_returns_bearer_token(client: AsyncClient, settings: Settings) -> None:
    """Successful login returns 200 with a valid bearer token."""
    resp = await client.post("/auth/login", json={"username": "roman", "password": "password123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert decode_access_token(body["access_token"], secret=settings.jwt_secret) is not None


async def test_login_wrong_password_401(client: AsyncClient) -> None:
    """Wrong password returns 401."""
    resp = await client.post("/auth/login", json={"username": "roman", "password": "nope"})
    assert resp.status_code == 401


async def test_login_missing_field_422(client: AsyncClient) -> None:
    """Missing required field returns 422."""
    resp = await client.post("/auth/login", json={"username": "roman"})
    assert resp.status_code == 422


async def test_protected_route_with_token(client: AsyncClient) -> None:
    """Authenticated request to GET /chats returns 200 with empty list."""
    token = (
        await client.post("/auth/login", json={"username": "roman", "password": "password123"})
    ).json()["access_token"]
    resp = await client.get("/chats", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == []


async def test_protected_route_without_token_401(client: AsyncClient) -> None:
    """Request without Authorization header returns 401."""
    assert (await client.get("/chats")).status_code == 401


async def test_protected_route_garbage_token_401(client: AsyncClient) -> None:
    """Request with a malformed token returns 401."""
    resp = await client.get("/chats", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401
