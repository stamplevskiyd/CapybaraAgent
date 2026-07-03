"""User registration orchestration."""

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
        """Create a user; raise UsernameTaken if the username already exists."""
        if await self._users.get_by_username(username) is not None:
            raise UsernameTaken(username)
        return await self._users.create(
            username=username,
            display_name=display_name,
            password_hash=hash_password(password),
        )
