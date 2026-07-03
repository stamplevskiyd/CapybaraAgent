"""User registration orchestration."""

from sqlalchemy.exc import IntegrityError

from capybara.db.models import User
from capybara.repositories.user_repo import UserRepo
from capybara.security.passwords import hash_password


class UsernameTaken(Exception):
    """Raised when registering a username that is already in use."""


class UserService:
    """Orchestrate user registration."""

    def __init__(self, users: UserRepo) -> None:
        """Initialize with user repository."""
        self._users = users

    async def register(self, display_name: str, username: str, password: str) -> User:
        """Create a user; raise UsernameTaken if the username already exists.

        The pre-check covers the common case.  A try/except around the insert
        catches the rare race where two requests pass the check simultaneously
        and the second flush violates the unique constraint, mapping the
        IntegrityError to UsernameTaken (→ 409) instead of propagating as 500.
        """
        if await self._users.get_by_username(username) is not None:
            raise UsernameTaken(username)
        try:
            return await self._users.create(
                username=username,
                display_name=display_name,
                password_hash=hash_password(password),
            )
        except IntegrityError as err:
            raise UsernameTaken(username) from err
