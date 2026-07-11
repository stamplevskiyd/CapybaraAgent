"""Delete one thread's chat preferences."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.commands.base import BaseCommand
from capybara.db.models import ChatPref
from capybara.filters import FieldEquals
from capybara.repositories.chat_pref_repo import ChatPrefRepo


class DeleteChatPref(BaseCommand[bool]):
    """Delete the thread's pref; the result reports whether it existed."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        user_id: UUID,
        thread_id: UUID,
    ) -> None:
        """Store the sessionmaker and the (user, thread) key."""
        self._sessionmaker = sessionmaker
        self._user_id = user_id
        self._thread_id = thread_id

    async def run(self) -> bool:
        """Delete the pref if present; return whether it existed."""
        async with self._sessionmaker() as session:
            repo = ChatPrefRepo(session)
            pref = await repo.get_one(
                FieldEquals(ChatPref.user_id, self._user_id),
                FieldEquals(ChatPref.thread_id, self._thread_id),
            )
            if pref is None:
                return False
            await repo.delete(pref)
            await session.commit()
            return True
