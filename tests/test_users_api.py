"""API tests for the POST /users registration endpoint."""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from capybara.api.dependencies import get_session
from capybara.db.models import User
from capybara.main import app


@pytest_asyncio.fixture
async def client(engine):  # type: ignore[no-untyped-def]
    """Provide an AsyncClient with a real session; clean up created users after each test."""
    from capybara.db.engine import create_sessionmaker

    maker = create_sessionmaker(engine)

    async def _override_session():  # type: ignore[return]
        async with maker() as sess:
            try:
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                raise

    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()

    async with maker() as cleanup:
        for row in (await cleanup.execute(select(User))).scalars().all():
            await cleanup.delete(row)
        await cleanup.commit()


async def test_register_success(client: AsyncClient, engine) -> None:  # type: ignore[no-untyped-def]
    """POST /users returns 201 with public fields and no password data."""
    resp = await client.post(
        "/users",
        json={"display_name": "Роман", "username": "roman", "password": "password123"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["username"] == "roman"
    assert body["display_name"] == "Роман"
    assert "password" not in body and "password_hash" not in body

    from capybara.db.engine import create_sessionmaker

    async with create_sessionmaker(engine)() as sess:
        user = (await sess.execute(select(User).where(User.username == "roman"))).scalar_one()
        assert user.password_hash.startswith("$argon2")
        assert user.password_hash != "password123"


async def test_register_duplicate_username_conflict(client: AsyncClient) -> None:
    """POST /users with a duplicate username returns 409."""
    payload = {"display_name": "Роман", "username": "roman2", "password": "password123"}
    assert (await client.post("/users", json=payload)).status_code == 201
    dup = await client.post(
        "/users",
        json={"display_name": "Other", "username": "roman2", "password": "password456"},
    )
    assert dup.status_code == 409


async def test_register_short_password_422(client: AsyncClient) -> None:
    """POST /users with a password shorter than 8 chars returns 422."""
    resp = await client.post(
        "/users",
        json={"display_name": "Роман", "username": "roman3", "password": "short"},
    )
    assert resp.status_code == 422


async def test_register_missing_field_422(client: AsyncClient) -> None:
    """POST /users without a required field returns 422."""
    resp = await client.post("/users", json={"username": "roman4", "password": "password123"})
    assert resp.status_code == 422


async def test_register_whitespace_only_fields_422(client: AsyncClient) -> None:
    """Whitespace-only registration fields are rejected as blank."""
    base = {"display_name": "Роман", "username": "roman5", "password": "password123"}
    for field, value in (
        ("display_name", "   "),
        ("username", "   "),
        ("password", "        "),
    ):
        payload = {**base, field: value}
        resp = await client.post("/users", json=payload)
        assert resp.status_code == 422, field
