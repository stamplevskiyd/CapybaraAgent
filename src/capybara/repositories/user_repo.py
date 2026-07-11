"""Repository for User model access."""

from capybara.db.models import User
from capybara.repositories.base import BaseRepository


class UserRepo(BaseRepository[User]):
    """Repository for User rows (inherited CRUD only)."""

    model = User
