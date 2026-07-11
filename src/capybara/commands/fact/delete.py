"""Delete a memory fact."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.commands.base import BaseCommand
from capybara.repositories.fact_repo import FactRepo


class DeleteFact(BaseCommand[bool]):
    """Delete a user-owned fact; the result reports whether anything was deleted."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        user_id: UUID,
        fact_id: UUID,
    ) -> None:
        """Store the sessionmaker and the fact to delete."""
        self._sessionmaker = sessionmaker
        self._user_id = user_id
        self._fact_id = fact_id

    async def run(self) -> bool:
        """Delete the fact if owned; return whether it existed."""
        async with self._sessionmaker() as session:
            repo = FactRepo(session)
            fact = await repo.get(self._fact_id)
            if fact is None or fact.user_id != self._user_id:
                return False
            await repo.delete(fact)
            await session.commit()
            return True
