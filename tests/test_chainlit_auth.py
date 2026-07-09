"""Tests for Chainlit header authentication against the app's JWT."""

from collections.abc import Awaitable, Callable

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.datastructures import Headers

from capybara.chainlit_app import resolve_user
from capybara.config import Settings
from capybara.db.engine import create_sessionmaker
from capybara.db.models import User
from capybara.security.tokens import create_access_token

MakeUser = Callable[..., Awaitable[User]]


@pytest_asyncio.fixture
async def sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Return an app-style sessionmaker bound to the test engine."""
    return create_sessionmaker(engine)


def _bearer(token: str) -> Headers:
    """Build request headers carrying a bearer token."""
    return Headers({"Authorization": f"Bearer {token}"})


async def test_resolve_user_accepts_a_valid_bearer_token(
    settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
    make_user: MakeUser,
) -> None:
    """A valid JWT resolves to a cl.User carrying the user's id in metadata."""
    async with sessionmaker() as session:
        user = await make_user(session, username="capy")
        await session.commit()
        user_id = user.id
    token = create_access_token(
        user_id, secret=settings.jwt_secret, ttl_minutes=60, algorithm=settings.jwt_algorithm
    )

    resolved = await resolve_user(_bearer(token), settings=settings, sessionmaker=sessionmaker)

    assert resolved is not None
    assert resolved.identifier == "capy"
    assert resolved.metadata["user_id"] == str(user_id)


@pytest.mark.parametrize(
    "headers",
    [
        Headers({}),
        Headers({"Authorization": "Token abc"}),
        Headers({"Authorization": "Bearer "}),
        Headers({"Authorization": "Bearer not-a-jwt"}),
    ],
)
async def test_resolve_user_rejects_bad_authorization(
    headers: Headers,
    settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Missing, malformed, wrong-scheme, or invalid tokens resolve to no user."""
    assert await resolve_user(headers, settings=settings, sessionmaker=sessionmaker) is None


async def test_resolve_user_rejects_token_for_unknown_user(
    settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """A validly-signed token for a user that no longer exists resolves to no user."""
    from uuid import uuid4

    token = create_access_token(
        uuid4(), secret=settings.jwt_secret, ttl_minutes=60, algorithm=settings.jwt_algorithm
    )

    assert await resolve_user(_bearer(token), settings=settings, sessionmaker=sessionmaker) is None
