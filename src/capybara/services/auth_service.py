"""Authentication (login) orchestration."""

from capybara.repositories.user_repo import UserRepo
from capybara.security.passwords import verify_password_async
from capybara.security.tokens import create_access_token


class InvalidCredentials(Exception):
    """Raised when a login has an unknown username or a wrong password."""


class AuthService:
    """Orchestrate login and JWT issuance."""

    def __init__(self, users: UserRepo, *, secret: str, ttl_minutes: int, algorithm: str) -> None:
        self._users = users
        self._secret = secret
        self._ttl_minutes = ttl_minutes
        self._algorithm = algorithm

    async def login(self, username: str, password: str) -> str:
        """Return a JWT for valid credentials; raise InvalidCredentials otherwise."""
        user = await self._users.get_by_username(username)
        if user is None or not await verify_password_async(password, user.password_hash):
            raise InvalidCredentials
        return create_access_token(
            user.id,
            secret=self._secret,
            ttl_minutes=self._ttl_minutes,
            algorithm=self._algorithm,
        )
