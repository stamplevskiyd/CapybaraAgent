"""Memory service: fact CRUD and semantic recall."""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.agent.model_registry import ModelRegistry
from capybara.config import Settings
from capybara.db.models import Fact
from capybara.repositories.fact_repo import FactRepo


class MemoryService:
    """Orchestrate long-term memory: fact CRUD and semantic recall.

    Owns short-lived sessions from the app-wide sessionmaker so it is safe to use both in a
    request and from a chat turn (it never borrows the request session).
    """

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        registry: ModelRegistry,
        settings: Settings,
    ) -> None:
        """Store the sessionmaker, model registry, and settings."""
        self._sessionmaker = sessionmaker
        self._registry = registry
        self._settings = settings

    async def list_facts(self, user_id: UUID) -> list[Fact]:
        """Return the user's facts, newest first."""
        async with self._sessionmaker() as session:
            return await FactRepo(session).list(Fact.user_id == user_id)

    async def add_fact(self, user_id: UUID, content: str, category: str) -> Fact:
        """Embed *content* and persist a new manual fact."""
        [embedding] = await self._registry.embed([content])
        async with self._sessionmaker() as session:
            fact = await FactRepo(session).create(
                user_id=user_id,
                content=content,
                category=category,
                embedding=embedding,
                source="manual",
            )
            await session.commit()
            return fact

    async def update_fact(
        self,
        user_id: UUID,
        fact_id: UUID,
        *,
        content: str | None = None,
        category: str | None = None,
    ) -> Fact | None:
        """Update a fact's content and/or category; new content is re-embedded.

        Returns the updated fact, or ``None`` if it does not exist or is not owned by
        *user_id* (defence in depth — the route already gates ownership).
        """
        fields: dict[str, Any] = {}
        if category is not None:
            fields["category"] = category
        if content is not None:
            fields["content"] = content
            # Embed before opening the session so the provider round-trip (a slow Ollama)
            # never holds a DB connection.
            [fields["embedding"]] = await self._registry.embed([content])
        async with self._sessionmaker() as session:
            repo = FactRepo(session)
            fact = await repo.get(fact_id)
            if fact is None or fact.user_id != user_id:
                return None
            fact = await repo.update(fact, **fields)
            await session.commit()
            await session.refresh(fact)
            return fact

    async def delete_fact(self, user_id: UUID, fact_id: UUID) -> bool:
        """Delete a fact if owned by *user_id*; return whether anything was deleted."""
        async with self._sessionmaker() as session:
            repo = FactRepo(session)
            fact = await repo.get(fact_id)
            if fact is None or fact.user_id != user_id:
                return False
            await repo.delete(fact)
            await session.commit()
            return True

    async def recall(self, user_id: UUID, query: str) -> list[Fact]:
        """Return facts semantically nearest to *query*, filtered by the min-similarity setting."""
        [embedding] = await self._registry.embed([query])
        async with self._sessionmaker() as session:
            results = await FactRepo(session).search(
                user_id, embedding, self._settings.memory_recall_k
            )
        min_similarity = self._settings.memory_recall_min_similarity
        return [fact for fact, distance in results if (1.0 - distance) >= min_similarity]
