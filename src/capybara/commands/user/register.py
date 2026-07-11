"""Register a local user."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.commands.base import BaseCommand
from capybara.db.models import User
from capybara.filters import FieldEquals
from capybara.repositories.user_repo import UserRepo
from capybara.security.passwords import hash_password_async


class UsernameTaken(Exception):
    """Raised when registering a username that is already in use."""


class RegisterUser(BaseCommand[User]):
    """Create a local user with an argon2-hashed password."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        display_name: str,
        username: str,
        password: str,
    ) -> None:
        """Store the sessionmaker and the registration payload."""
        self._sessionmaker = sessionmaker
        self._display_name = display_name
        self._username = username
        self._password = password

    async def validate(self) -> None:
        """Reject a username that is already taken (covers the common case).

        Raises:
            UsernameTaken: If a user with this username already exists.
        """
        async with self._sessionmaker() as session:
            existing = await UserRepo(session).get_one(FieldEquals(User.username, self._username))
        if existing is not None:
            raise UsernameTaken(self._username)

    async def run(self) -> User:
        """Hash the password and insert the user.

        The unique index on username backstops the race where two registrations pass
        ``validate`` simultaneously — it is the table's only unique constraint, so any
        integrity failure on this insert is a username collision.

        Raises:
            UsernameTaken: If the insert hits the unique-username constraint.
        """
        password_hash = await hash_password_async(self._password)
        async with self._sessionmaker() as session:
            try:
                user = await UserRepo(session).create(
                    username=self._username,
                    display_name=self._display_name,
                    password_hash=password_hash,
                )
                await session.commit()
            except IntegrityError as err:
                raise UsernameTaken(self._username) from err
            return user
