"""List a user's memory facts."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.commands.base import BaseCommand
from capybara.db.models import Fact
from capybara.filters import FieldEquals
from capybara.repositories.fact_repo import FactRepo


class ListFacts(BaseCommand[list[Fact]]):
    """Return the user's facts, newest first."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], *, user_id: UUID) -> None:
        """Store the sessionmaker and the owner."""
        self._sessionmaker = sessionmaker
        self._user_id = user_id

    async def run(self) -> list[Fact]:
        """List the user's facts in the repo's newest-first order."""
        async with self._sessionmaker() as session:
            return await FactRepo(session).get_list(FieldEquals(Fact.user_id, self._user_id))
