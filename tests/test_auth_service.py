import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from capybara.repositories.user_repo import UserRepo
from capybara.security.tokens import decode_access_token
from capybara.services.auth_service import AuthService, InvalidCredentials

SECRET = "svc-test-secret"


def _service(session: AsyncSession) -> AuthService:
    return AuthService(UserRepo(session), secret=SECRET, ttl_minutes=60, algorithm="HS256")


async def test_login_success_returns_token_for_user(session: AsyncSession, make_user) -> None:  # type: ignore[no-untyped-def]
    user = await make_user(session, username="roman", password="password123")
    token = await _service(session).login("roman", "password123")
    assert decode_access_token(token, secret=SECRET) == user.id


async def test_login_wrong_password_raises(session: AsyncSession, make_user) -> None:  # type: ignore[no-untyped-def]
    await make_user(session, username="roman", password="password123")
    with pytest.raises(InvalidCredentials):
        await _service(session).login("roman", "wrong-password")


async def test_login_unknown_user_raises(session: AsyncSession) -> None:
    with pytest.raises(InvalidCredentials):
        await _service(session).login("nobody", "password123")
