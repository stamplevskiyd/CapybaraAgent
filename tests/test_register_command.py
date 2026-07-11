"""Tests for the RegisterUser command."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.commands.user.register import RegisterUser, UsernameTaken


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


async def test_register_creates_user_with_hashed_password(session: AsyncSession) -> None:
    """RegisterUser creates a user with an argon2-hashed password."""
    user = await RegisterUser(
        _maker(session), display_name="Роман", username="roman", password="password123"
    ).execute()
    assert user.username == "roman"
    assert user.display_name == "Роман"
    assert user.password_hash.startswith("$argon2")
    assert user.password_hash != "password123"


async def test_register_duplicate_username_raises(session: AsyncSession, make_user) -> None:  # type: ignore[no-untyped-def]
    """validate() rejects a username that already exists."""
    await make_user(session, username="roman", display_name="Роман")
    with pytest.raises(UsernameTaken):
        await RegisterUser(
            _maker(session), display_name="Other", username="roman", password="password123"
        ).execute()


async def test_register_race_maps_integrity_error(session: AsyncSession, make_user) -> None:  # type: ignore[no-untyped-def]
    """The unique index backstops the race where two registrations pass validate().

    Calling run() directly skips the validate() pre-check, forcing the insert to hit
    the unique-username constraint — which must surface as UsernameTaken, not a 500.
    """
    await make_user(session, username="roman", display_name="Роман")
    command = RegisterUser(
        _maker(session), display_name="Other", username="roman", password="password123"
    )
    with pytest.raises(UsernameTaken):
        await command.run()
