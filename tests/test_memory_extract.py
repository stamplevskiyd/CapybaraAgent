"""Tests for auto-capture: extract_and_store + schedule_extraction (Task 8)."""

from sqlalchemy.ext.asyncio import AsyncEngine

from capybara.config import Settings
from capybara.db.engine import create_sessionmaker
from capybara.db.models import Chat
from capybara.repositories.fact_repo import FactRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.services.memory_service import MemoryService
from support import StubMemoryAgent


async def _seed_turn(maker, make_user, *, username, auto_capture=True):  # type: ignore[no-untyped-def]
    async with maker() as s:
        user = await make_user(s, username=username, display_name=username)
        user.memory_auto_capture = auto_capture
        chat = Chat(user_id=user.id, title="c", model="test-model")
        s.add(chat)
        await s.flush()
        repo = MessageRepo(s)
        await repo.create(chat_id=chat.id, role="user", content="Меня зовут Роман, люблю чай")
        await repo.create(chat_id=chat.id, role="assistant", content="Приятно, Роман!")
        await s.commit()
        return user.id, chat.id


async def test_extract_inserts_new_facts(  # type: ignore[no-untyped-def]
    engine: AsyncEngine, settings: Settings, make_user
) -> None:
    """Extracted facts should be inserted with source='auto'."""
    maker = create_sessionmaker(engine)
    user_id, chat_id = await _seed_turn(maker, make_user, username="ex1")
    agent = StubMemoryAgent(
        settings,
        embeddings={"Любит чай": [1.0] + [0.0] * 767},
        extracted={"facts": [{"content": "Любит чай", "category": "preference"}]},
    )
    await MemoryService(maker, agent, settings).extract_and_store(user_id, chat_id)

    async with maker() as s:
        facts = await FactRepo(s).list()
    assert [f.content for f in facts] == ["Любит чай"]
    assert facts[0].source == "auto"


async def test_extract_skips_near_duplicates(  # type: ignore[no-untyped-def]
    engine: AsyncEngine, settings: Settings, make_user
) -> None:
    """Candidates whose nearest existing fact similarity >= dedup threshold must be skipped."""
    maker = create_sessionmaker(engine)
    user_id, chat_id = await _seed_turn(maker, make_user, username="ex2")
    vec = [1.0] + [0.0] * 767
    async with maker() as s:
        await FactRepo(s).create(
            user_id=user_id,
            category="preference",
            content="Любит чай",
            embedding=vec,
            source="manual",
        )
        await s.commit()

    agent = StubMemoryAgent(
        settings,
        embeddings={"Обожает чай": vec},  # identical vector → similarity 1.0 ≥ dedup threshold
        extracted={"facts": [{"content": "Обожает чай", "category": "preference"}]},
    )
    await MemoryService(maker, agent, settings).extract_and_store(user_id, chat_id)

    async with maker() as s:
        facts = await FactRepo(s).list()
    assert len(facts) == 1  # duplicate skipped


async def test_extract_noop_when_disabled(  # type: ignore[no-untyped-def]
    engine: AsyncEngine, settings: Settings, make_user
) -> None:
    """When auto-capture is disabled for the user, no facts should be inserted."""
    maker = create_sessionmaker(engine)
    user_id, chat_id = await _seed_turn(maker, make_user, username="ex3", auto_capture=False)
    agent = StubMemoryAgent(
        settings,
        extracted={"facts": [{"content": "anything", "category": "personal"}]},
    )
    await MemoryService(maker, agent, settings).extract_and_store(user_id, chat_id)

    async with maker() as s:
        facts = await FactRepo(s).list()
    assert facts == []


async def test_schedule_extraction_swallows_errors(  # type: ignore[no-untyped-def]
    engine: AsyncEngine, settings: Settings, make_user
) -> None:
    """schedule_extraction must never raise, even for a bogus user/chat."""
    from uuid import uuid4

    from capybara.services.memory_service import schedule_extraction

    maker = create_sessionmaker(engine)
    service = MemoryService(maker, StubMemoryAgent(settings), settings)
    # Non-existent user/chat → extract_and_store no-ops; schedule must never raise.
    await schedule_extraction(service, uuid4(), uuid4())
