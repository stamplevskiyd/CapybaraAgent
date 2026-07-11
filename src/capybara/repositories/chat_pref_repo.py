"""Repository for ChatPref model access."""

from capybara.db.models import ChatPref
from capybara.repositories.base import BaseRepository


class ChatPrefRepo(BaseRepository[ChatPref]):
    """Repository for per-thread chat preferences (inherited CRUD only)."""

    model = ChatPref
