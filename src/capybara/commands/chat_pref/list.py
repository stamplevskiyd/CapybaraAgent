"""List a user's per-thread chat preferences."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.commands.base import BaseCommand
from capybara.db.models import ChatPref
from capybara.filters import FieldEquals
from capybara.repositories.chat_pref_repo import ChatPrefRepo


class ListChatPrefs(BaseCommand[list[ChatPref]]):
    """Return all of the user's chat prefs (merged into the thread list by the client)."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], *, user_id: UUID) -> None:
        """Store the sessionmaker and the owner."""
        self._sessionmaker = sessionmaker
        self._user_id = user_id

    async def run(self) -> list[ChatPref]:
        """List the user's prefs."""
        async with self._sessionmaker() as session:
            return await ChatPrefRepo(session).get_list(
                FieldEquals(ChatPref.user_id, self._user_id)
            )
