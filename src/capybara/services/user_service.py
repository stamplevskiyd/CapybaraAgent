"""User registration orchestration."""

from sqlalchemy.exc import IntegrityError

from capybara.db.models import User
from capybara.repositories.user_repo import UserRepo
from capybara.security.passwords import hash_password_async


class UsernameTaken(Exception):
    """Raised when registering a username that is already in use."""


class UserService:
    """Orchestrate user registration."""

    def __init__(self, users: UserRepo) -> None:
        """Initialize with user repository."""
        self._users = users

    async def register(self, display_name: str, username: str, password: str) -> User:
        """Create a user; raise UsernameTaken if the username already exists.

        The pre-check covers the common case. The unique index on username backstops
        the race where two registrations pass the check simultaneously — it is the
        table's only unique constraint, so any integrity failure on this insert is a
        username collision.
        """
        if await self._users.get_by_username(username) is not None:
            raise UsernameTaken(username)
        password_hash = await hash_password_async(password)
        try:
            return await self._users.create(
                username=username,
                display_name=display_name,
                password_hash=password_hash,
            )
        except IntegrityError as err:
            raise UsernameTaken(username) from err
