from capybara.db.models import User
from capybara.repositories.base import BaseRepository


class UserRepo(BaseRepository[User]):
    model = User
