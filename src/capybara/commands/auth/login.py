"""Log a user in and issue a JWT."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.commands.base import BaseCommand
from capybara.db.models import User
from capybara.filters import FieldEquals
from capybara.repositories.user_repo import UserRepo
from capybara.security.passwords import verify_password_async
from capybara.security.tokens import create_access_token


class InvalidCredentials(Exception):
    """Raised when a login has an unknown username or a wrong password."""


class LoginUser(BaseCommand[str]):
    """Verify credentials and return a signed JWT access token."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        username: str,
        password: str,
        secret: str,
        ttl_minutes: int,
        algorithm: str,
    ) -> None:
        """Store the sessionmaker, the credentials, and the JWT parameters."""
        self._sessionmaker = sessionmaker
        self._username = username
        self._password = password
        self._secret = secret
        self._ttl_minutes = ttl_minutes
        self._algorithm = algorithm

    async def run(self) -> str:
        """Return a JWT for valid credentials.

        Raises:
            InvalidCredentials: On an unknown username or a wrong password.
        """
        async with self._sessionmaker() as session:
            user = await UserRepo(session).get_one(FieldEquals(User.username, self._username))
        if user is None or not await verify_password_async(self._password, user.password_hash):
            raise InvalidCredentials
        return create_access_token(
            user.id,
            secret=self._secret,
            ttl_minutes=self._ttl_minutes,
            algorithm=self._algorithm,
        )
