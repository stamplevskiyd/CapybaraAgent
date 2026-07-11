"""Create a manual memory fact."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.agent.model_registry import ModelRegistry
from capybara.commands.base import BaseCommand
from capybara.db.models import Fact
from capybara.repositories.fact_repo import FactRepo


class CreateFact(BaseCommand[Fact]):
    """Embed *content* and persist a new manual fact for the user."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        registry: ModelRegistry,
        *,
        user_id: UUID,
        content: str,
        category: str,
    ) -> None:
        """Store dependencies and the fact to create."""
        self._sessionmaker = sessionmaker
        self._registry = registry
        self._user_id = user_id
        self._content = content
        self._category = category

    async def run(self) -> Fact:
        """Embed the content, then persist the fact as ``source="manual"``."""
        [embedding] = await self._registry.embed([self._content])
        async with self._sessionmaker() as session:
            fact = await FactRepo(session).create(
                user_id=self._user_id,
                content=self._content,
                category=self._category,
                embedding=embedding,
                source="manual",
            )
            await session.commit()
            return fact
