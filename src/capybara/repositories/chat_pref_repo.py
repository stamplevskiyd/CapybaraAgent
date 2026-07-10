"""Repository for ChatPref model access."""

from uuid import UUID

from sqlalchemy import select

from capybara.db.models import ChatPref
from capybara.repositories.base import BaseRepository


class ChatPrefRepo(BaseRepository[ChatPref]):
    """Repository for per-thread chat preferences."""

    model = ChatPref

    async def get_for_thread(self, user_id: UUID, thread_id: UUID) -> ChatPref | None:
        """Return the user's pref for a thread, or None if none is set."""
        stmt = select(ChatPref).where(ChatPref.user_id == user_id, ChatPref.thread_id == thread_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()
