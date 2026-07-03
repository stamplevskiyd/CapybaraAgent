"""Repository for User model access."""

from sqlalchemy import select

from capybara.db.models import User
from capybara.repositories.base import BaseRepository


class UserRepo(BaseRepository[User]):
    """Repository for User CRUD operations."""

    model = User

    async def get_by_username(self, username: str) -> User | None:
        """Return the user with the given username, or None if there is none."""
        stmt = select(User).where(User.username == username)
        return (await self._session.execute(stmt)).scalar_one_or_none()
