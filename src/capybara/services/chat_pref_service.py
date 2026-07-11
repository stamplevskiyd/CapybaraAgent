"""Chat-pref service: per-user favorite/model metadata for Chainlit threads."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.db.models import ChatPref
from capybara.repositories.chat_pref_repo import ChatPrefRepo


class ChatPrefService:
    """Manage per-thread chat preferences (favorite, selected model) for a user.

    Owns short-lived sessions from the app-wide sessionmaker (never borrows a request
    session), matching the other extension services.
    """

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Store the app-wide sessionmaker."""
        self._sessionmaker = sessionmaker

    async def list_prefs(self, user_id: UUID) -> list[ChatPref]:
        """Return all of the user's chat prefs."""
        async with self._sessionmaker() as session:
            return await ChatPrefRepo(session).list(ChatPref.user_id == user_id)

    async def upsert(
        self, user_id: UUID, thread_id: UUID, *, is_favorite: bool, model: str | None
    ) -> ChatPref:
        """Create the thread's pref, or replace its fields if it already exists."""
        async with self._sessionmaker() as session:
            repo = ChatPrefRepo(session)
            pref = await repo.get_for_thread(user_id, thread_id)
            if pref is None:
                pref = await repo.create(
                    user_id=user_id,
                    thread_id=thread_id,
                    is_favorite=is_favorite,
                    model=model,
                )
            else:
                pref = await repo.update(pref, is_favorite=is_favorite, model=model)
            await session.commit()
            return pref

    async def delete(self, user_id: UUID, thread_id: UUID) -> bool:
        """Delete the thread's pref; return whether it existed."""
        async with self._sessionmaker() as session:
            repo = ChatPrefRepo(session)
            pref = await repo.get_for_thread(user_id, thread_id)
            if pref is None:
                return False
            await repo.delete(pref)
            await session.commit()
            return True
