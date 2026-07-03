"""Tests for UserService user registration."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from capybara.db.models import User
from capybara.repositories.user_repo import UserRepo
from capybara.security.passwords import hash_password
from capybara.services.user_service import UsernameTaken, UserService


async def test_register_creates_user_with_hashed_password(session: AsyncSession) -> None:
    """Test that register creates a user with argon2-hashed password."""
    service = UserService(UserRepo(session))
    user = await service.register("Роман", "roman", "password123")
    assert user.username == "roman"
    assert user.display_name == "Роман"
    assert user.password_hash.startswith("$argon2")
    assert user.password_hash != "password123"


async def test_register_duplicate_username_raises(session: AsyncSession) -> None:
    """Test that register raises UsernameTaken for duplicate username."""
    user = User(username="roman", display_name="Роман", password_hash=hash_password("x"))
    session.add(user)
    await session.flush()
    service = UserService(UserRepo(session))
    with pytest.raises(UsernameTaken):
        await service.register("Other", "roman", "password123")


async def test_register_race_maps_integrity_error(
    session: AsyncSession, make_user: object
) -> None:
    """Test that an IntegrityError from the DB is caught and re-raised as UsernameTaken.

    Simulates the race where two requests both pass the pre-check but the
    second flush violates the unique constraint on users.username.
    The row is inserted first; then get_by_username is patched to return None
    so the pre-check is bypassed, forcing the except branch to fire.
    """
    await make_user(session, username="roman", display_name="Роман")  # type: ignore[call-arg]
    repo = UserRepo(session)

    async def _always_none(username: str) -> None:
        return None

    repo.get_by_username = _always_none  # type: ignore[method-assign]

    service = UserService(repo)
    with pytest.raises(UsernameTaken):
        await service.register("Other", "roman", "password123")
