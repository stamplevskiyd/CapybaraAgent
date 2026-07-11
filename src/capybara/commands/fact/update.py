"""Update a memory fact's content and/or category."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.agent.model_registry import ModelRegistry
from capybara.commands.base import BaseCommand
from capybara.db.models import Fact
from capybara.repositories.fact_repo import FactRepo


class UpdateFact(BaseCommand[Fact | None]):
    """Apply a partial update to a user-owned fact; new content is re-embedded."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        registry: ModelRegistry,
        *,
        user_id: UUID,
        fact_id: UUID,
        patch: BaseModel,
    ) -> None:
        """Store dependencies, the target fact, and the partial payload."""
        self._sessionmaker = sessionmaker
        self._registry = registry
        self._user_id = user_id
        self._fact_id = fact_id
        self._patch = patch

    async def run(self) -> Fact | None:
        """Update the fact; return None if it does not exist or is not owned.

        The ownership check lives here (not in ``validate``) so it shares the writing
        session — no window for the fact to vanish between check and update.
        """
        fields: dict[str, Any] = self._patch.model_dump(exclude_unset=True, exclude_none=True)
        if "content" in fields:
            # Embed before opening the session so the provider round-trip (a slow
            # Ollama) never holds a DB connection.
            [fields["embedding"]] = await self._registry.embed([fields["content"]])
        async with self._sessionmaker() as session:
            repo = FactRepo(session)
            fact = await repo.get(self._fact_id)
            if fact is None or fact.user_id != self._user_id:
                return None
            fact = await repo.update(fact, **fields)
            await session.commit()
            await session.refresh(fact)
            return fact
