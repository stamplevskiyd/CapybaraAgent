"""Memory service: fact CRUD, semantic recall, and (Task 8) auto-capture."""

import logging
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.agent.model_registry import ModelRegistry
from capybara.config import Settings
from capybara.db.models import Fact, Message, User
from capybara.filters import FieldEquals
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.fact_repo import FactRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.services.event_bus import EventBus

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
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        registry: ModelRegistry,
        settings: Settings,
        event_bus: EventBus | None = None,
    ) -> None:
        """Store the sessionmaker, model registry, settings, and optional event bus."""
        self._sessionmaker = sessionmaker
        self._registry = registry
        self._settings = settings
        self._event_bus = event_bus

    async def list_facts(self, user_id: UUID) -> list[Fact]:
        """Return the user's facts, newest first."""
        async with self._sessionmaker() as session:
            return await FactRepo(session).list(FieldEquals(Fact.user_id, user_id))

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
        # Read first on a short session; the embedding call (a provider round-trip) then
        # runs with no DB connection held, so a slow Ollama can't exhaust the pool.
        async with self._sessionmaker() as session:
            fact = await FactRepo(session).get(fact_id)
            if fact is None or fact.user_id != user_id:
                return None
            current_content = fact.content
        fields: dict[str, Any] = {}
        if category is not None:
            fields["category"] = category
        if content is not None and content != current_content:
            fields["content"] = content
            [fields["embedding"]] = await self._registry.embed([content])
        if not fields:
            return fact  # nothing to change; return the row read above
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

    async def get_auto_capture(self, user_id: UUID) -> bool:
        """Return the user's auto-capture toggle.

        Raises:
            LookupError: If no user with *user_id* exists (an authenticated caller's
                row vanishing mid-request is an internal inconsistency, surfaced
                explicitly rather than via an ``assert`` that ``-O`` would strip).
        """
        async with self._sessionmaker() as session:
            user = await session.get(User, user_id)
            if user is None:
                raise LookupError(f"User {user_id} not found")
            return user.memory_auto_capture

    async def set_auto_capture(self, user_id: UUID, value: bool) -> bool:
        """Persist the user's auto-capture toggle and return the new value.

        Raises:
            LookupError: If no user with *user_id* exists (see ``get_auto_capture``).
        """
        async with self._sessionmaker() as session:
            user = await session.get(User, user_id)
            if user is None:
                raise LookupError(f"User {user_id} not found")
            user.memory_auto_capture = value
            await session.commit()
            return value

    async def extract_and_store(self, user_id: UUID, chat_id: UUID) -> None:
        """Extract durable facts from a chat's last turn and store the novel ones.

        Gated by the user's auto-capture flag. Uses the chat's own model for extraction and
        embedding-similarity dedup (facts within ``memory_dedup_threshold`` of an existing
        fact are skipped). Safe to run in a post-response background task.
        """
        # Best-effort per turn: post-response run; incomplete=False filter and dedup keep this safe.
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
        last_assistant = next((m for m in reversed(messages) if m.role == "assistant"), None)
        turn = _last_turn_text(messages)
        if turn is None or last_assistant is None:
            return
        assistant_id = last_assistant.id

        extracted = await self._registry.run_structured(
            model, EXTRACTION_SYSTEM_PROMPT, turn, ExtractedFacts
        )
        saved: list[ExtractedFact] = []
        for candidate in extracted.facts:
            [embedding] = await self._registry.embed([candidate.content])
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
            saved.append(candidate)

        if not saved:
            return
        facts_payload = [{"content": f.content, "category": f.category} for f in saved]
        async with self._sessionmaker() as session:
            repo_m = MessageRepo(session)
            message = await repo_m.get(assistant_id)
            if message is None:
                # Message was deleted between extraction and write; skip publish so
                # subscribers never receive an event pointing at a missing row.
                return
            await repo_m.update(message, memory_saves=facts_payload)
            await session.commit()
        if self._event_bus is not None:
            await self._event_bus.publish(
                user_id,
                {
                    "event": "memory-save",
                    "data": {
                        "chat_id": str(chat_id),
                        "message_id": str(assistant_id),
                        "facts": facts_payload,
                    },
                },
            )


async def schedule_extraction(service: MemoryService, user_id: UUID, chat_id: UUID) -> None:
    """Run auto-capture as a background task, swallowing and logging every error.

    Variant A stand-in for a real task queue: the endpoint attaches this via Starlette's
    ``BackgroundTask``. When the Celery slice lands, only the trigger changes.
    """
    try:
        await service.extract_and_store(user_id, chat_id)
    except Exception:
        logger.exception("auto-capture failed for chat %s", chat_id)
