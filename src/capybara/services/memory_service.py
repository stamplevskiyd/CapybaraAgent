"""Memory service: fact CRUD, semantic recall, and (Task 8) auto-capture."""

import logging
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.agent.base import BaseAgent
from capybara.config import Settings
from capybara.db.models import Fact, Message, User
from capybara.filters import FieldEquals
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.fact_repo import FactRepo
from capybara.repositories.message_repo import MessageRepo

logger = logging.getLogger(__name__)

FactCategory = Literal["personal", "project", "preference"]


class ExtractedFact(BaseModel):
    """A single fact the extraction model proposes from a conversation turn."""

    content: str
    category: FactCategory


class ExtractedFacts(BaseModel):
    """Structured extraction output: zero or more candidate facts."""

    facts: list[ExtractedFact]


#: Extraction prompt used by ``extract_and_store`` (Task 8).
EXTRACTION_SYSTEM_PROMPT = (
    "Extract durable, user-specific facts worth remembering long-term from the "
    "conversation turn: personal details, ongoing projects, and stated preferences. "
    "Categorise each as 'personal', 'project', or 'preference'. Ignore transient chatter, "
    "questions, and general knowledge. Return an empty list if there is nothing worth storing."
)


def _last_turn_text(messages: list[Message]) -> str | None:
    r"""Format the last user+assistant exchange as ``User: …\nAssistant: …``.

    Returns ``None`` when there is no completed assistant reply with a preceding user
    message — nothing to extract from.
    """
    last_assistant = next((m for m in reversed(messages) if m.role == "assistant"), None)
    if last_assistant is None:
        return None
    last_user = next(
        (m for m in reversed(messages) if m.role == "user" and m.seq < last_assistant.seq), None
    )
    if last_user is None:
        return None
    return f"User: {last_user.content}\nAssistant: {last_assistant.content}"


class MemoryService:
    """Orchestrate long-term memory: fact CRUD, recall, and auto-capture.

    Owns short-lived sessions from the app-wide sessionmaker so it is safe to use both in a
    request and in a post-response background task (it never borrows the request session).
    """

    def __init__(
        self, sessionmaker: async_sessionmaker[AsyncSession], agent: BaseAgent, settings: Settings
    ) -> None:
        """Store the sessionmaker, provider agent, and settings."""
        self._sessionmaker = sessionmaker
        self._agent = agent
        self._settings = settings

    async def list_facts(self, user_id: UUID) -> list[Fact]:
        """Return the user's facts, newest first."""
        async with self._sessionmaker() as session:
            return await FactRepo(session).list(FieldEquals(Fact.user_id, user_id))

    async def add_fact(self, user_id: UUID, content: str, category: str) -> Fact:
        """Embed *content* and persist a new manual fact."""
        [embedding] = await self._agent.embed([content])
        async with self._sessionmaker() as session:
            fact = await FactRepo(session).create(
                user_id=user_id,
                content=content,
                category=category,
                embedding=embedding,
                source="manual",
            )
            await session.commit()
            await session.refresh(fact)
            return fact

    async def update_fact(
        self,
        user_id: UUID,
        fact_id: UUID,
        *,
        content: str | None = None,
        category: str | None = None,
    ) -> Fact | None:
        """Update a fact's content and/or category; re-embed only when content changes.

        Returns the updated fact, or ``None`` if it does not exist or is not owned by
        *user_id* (defence in depth — the route already gates ownership).
        """
        async with self._sessionmaker() as session:
            repo = FactRepo(session)
            fact = await repo.get(fact_id)
            if fact is None or fact.user_id != user_id:
                return None
            fields: dict[str, Any] = {}
            if category is not None:
                fields["category"] = category
            if content is not None and content != fact.content:
                fields["content"] = content
                [fields["embedding"]] = await self._agent.embed([content])
            if fields:
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
        [embedding] = await self._agent.embed([query])
        async with self._sessionmaker() as session:
            results = await FactRepo(session).search(
                user_id, embedding, self._settings.memory_recall_k
            )
        min_similarity = self._settings.memory_recall_min_similarity
        return [fact for fact, distance in results if (1.0 - distance) >= min_similarity]

    async def get_auto_capture(self, user_id: UUID) -> bool:
        """Return the user's auto-capture toggle."""
        async with self._sessionmaker() as session:
            user = await session.get(User, user_id)
            assert user is not None
            return user.memory_auto_capture

    async def set_auto_capture(self, user_id: UUID, value: bool) -> bool:
        """Persist the user's auto-capture toggle and return the new value."""
        async with self._sessionmaker() as session:
            user = await session.get(User, user_id)
            assert user is not None
            user.memory_auto_capture = value
            await session.commit()
            return value

    async def extract_and_store(self, user_id: UUID, chat_id: UUID) -> None:
        """Extract durable facts from a chat's last turn and store the novel ones.

        Gated by the user's auto-capture flag. Uses the chat's own model for extraction and
        embedding-similarity dedup (facts within ``memory_dedup_threshold`` of an existing
        fact are skipped). Safe to run in a post-response background task.
        """
        async with self._sessionmaker() as session:
            user = await session.get(User, user_id)
            if user is None or not user.memory_auto_capture:
                return
            chat = await ChatRepo(session).get(chat_id)
            if chat is None or chat.model is None:
                return
            model = chat.model
            messages = await MessageRepo(session).list(
                FieldEquals(Message.chat_id, chat_id),
                FieldEquals(Message.incomplete, False),
            )
        turn = _last_turn_text(messages)
        if turn is None:
            return

        extracted = await self._agent.run_structured(
            model, EXTRACTION_SYSTEM_PROMPT, turn, ExtractedFacts
        )
        for candidate in extracted.facts:
            [embedding] = await self._agent.embed([candidate.content])
            async with self._sessionmaker() as session:
                repo = FactRepo(session)
                nearest = await repo.search(user_id, embedding, 1)
                if nearest and (1.0 - nearest[0][1]) >= self._settings.memory_dedup_threshold:
                    continue
                await repo.create(
                    user_id=user_id,
                    content=candidate.content,
                    category=candidate.category,
                    embedding=embedding,
                    source="auto",
                )
                await session.commit()


async def schedule_extraction(service: MemoryService, user_id: UUID, chat_id: UUID) -> None:
    """Run auto-capture as a background task, swallowing and logging every error.

    Variant A stand-in for a real task queue: the endpoint attaches this via Starlette's
    ``BackgroundTask``. When the Celery slice lands, only the trigger changes.
    """
    try:
        await service.extract_and_store(user_id, chat_id)
    except Exception:
        logger.exception("auto-capture failed for chat %s", chat_id)
