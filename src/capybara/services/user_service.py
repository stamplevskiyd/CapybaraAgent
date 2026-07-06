"""User registration orchestration."""

from sqlalchemy.exc import IntegrityError

from capybara.db.models import User
from capybara.repositories.user_repo import UserRepo
from capybara.security.passwords import hash_password_async

# Name of the unique index on users.username (see the initial migration); a
# violation of this specific constraint is the only IntegrityError we translate
# into a 409 UsernameTaken.
_USERNAME_UNIQUE = "ix_users_username"


def _is_username_conflict(err: IntegrityError) -> bool:
    """Return True only if *err* is a unique violation on the username index."""
    constraint = getattr(err.orig, "constraint_name", None)
    if constraint is not None:
        return bool(constraint == _USERNAME_UNIQUE)
    # Fall back to matching the constraint name in the driver message when the
    # DBAPI does not expose it as a structured attribute.
    return _USERNAME_UNIQUE in str(err.orig)


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
        and the second flush violates the unique constraint, mapping *only* that
        conflict to UsernameTaken (→ 409); any other IntegrityError propagates.
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
            if _is_username_conflict(err):
                raise UsernameTaken(username) from err
            raise
