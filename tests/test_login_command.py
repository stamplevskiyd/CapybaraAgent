"""Tests for the LoginUser command."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.commands.auth.login import InvalidCredentials, LoginUser
from capybara.security.tokens import decode_access_token

SECRET = "test-jwt-secret-key-with-at-least-32-bytes!!"


def _maker(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    """A sessionmaker that always hands back the test's transactional session."""
    from contextlib import asynccontextmanager

    class _Maker:
        def __call__(self):  # type: ignore[no-untyped-def]
            @asynccontextmanager
            async def _cm():  # type: ignore[no-untyped-def]
                yield session

            return _cm()

    return _Maker()  # type: ignore[return-value]


def _command(session: AsyncSession, username: str, password: str) -> LoginUser:
    return LoginUser(
        _maker(session),
        username=username,
        password=password,
        secret=SECRET,
        ttl_minutes=60,
        algorithm="HS256",
    )


async def test_login_success_returns_token_for_user(session: AsyncSession, make_user) -> None:  # type: ignore[no-untyped-def]
    user = await make_user(session, username="roman", password="password123")
    token = await _command(session, "roman", "password123").execute()
    assert decode_access_token(token, secret=SECRET) == user.id


async def test_login_wrong_password_raises(session: AsyncSession, make_user) -> None:  # type: ignore[no-untyped-def]
    await make_user(session, username="roman", password="password123")
    with pytest.raises(InvalidCredentials):
        await _command(session, "roman", "wrong-password").execute()


async def test_login_unknown_user_raises(session: AsyncSession) -> None:
    with pytest.raises(InvalidCredentials):
        await _command(session, "nobody", "password123").execute()
