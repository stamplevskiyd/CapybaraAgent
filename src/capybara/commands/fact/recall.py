"""Semantic recall over a user's memory facts."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.agent.model_registry import ModelRegistry
from capybara.commands.base import BaseCommand
from capybara.config import Settings
from capybara.db.models import Fact
from capybara.repositories.fact_repo import FactRepo


class RecallFacts(BaseCommand[list[Fact]]):
    """Return facts semantically nearest to a query, filtered by min similarity."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        registry: ModelRegistry,
        settings: Settings,
        *,
        user_id: UUID,
        query: str,
    ) -> None:
        """Store dependencies, the owner, and the recall query."""
        self._sessionmaker = sessionmaker
        self._registry = registry
        self._settings = settings
        self._user_id = user_id
        self._query = query

    async def run(self) -> list[Fact]:
        """Embed the query, search nearest facts, and apply the similarity threshold."""
        [embedding] = await self._registry.embed([self._query])
        async with self._sessionmaker() as session:
            results = await FactRepo(session).search(
                self._user_id, embedding, self._settings.memory_recall_k
            )
        min_similarity = self._settings.memory_recall_min_similarity
        return [fact for fact, distance in results if (1.0 - distance) >= min_similarity]
