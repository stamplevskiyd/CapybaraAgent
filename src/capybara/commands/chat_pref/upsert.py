"""Set a thread's chat preferences (favorite flag, selected model, agent mode)."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.commands.base import BaseCommand
from capybara.db.models import ChatPref
from capybara.filters import FieldEquals
from capybara.repositories.chat_pref_repo import ChatPrefRepo


class UpsertChatPref(BaseCommand[ChatPref]):
    """Create the thread's pref, or replace its fields if it already exists."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        user_id: UUID,
        thread_id: UUID,
        is_favorite: bool,
        model: str | None,
        mode: str,
    ) -> None:
        """Store the sessionmaker, the (user, thread) key, and the new field values."""
        self._sessionmaker = sessionmaker
        self._user_id = user_id
        self._thread_id = thread_id
        self._is_favorite = is_favorite
        self._model = model
        self._mode = mode

    async def run(self) -> ChatPref:
        """Create or replace the pref within one session (PUT semantics)."""
        async with self._sessionmaker() as session:
            repo = ChatPrefRepo(session)
            pref = await repo.get_one(
                FieldEquals(ChatPref.user_id, self._user_id),
                FieldEquals(ChatPref.thread_id, self._thread_id),
            )
            if pref is None:
                pref = await repo.create(
                    user_id=self._user_id,
                    thread_id=self._thread_id,
                    is_favorite=self._is_favorite,
                    model=self._model,
                    mode=self._mode,
                )
            else:
                pref = await repo.update(
                    pref, is_favorite=self._is_favorite, model=self._model, mode=self._mode
                )
            await session.commit()
            return pref
