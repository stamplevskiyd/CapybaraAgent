import asyncio

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine

from capybara.config import Settings
from capybara.db.engine import create_sessionmaker
from capybara.db.models import User
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.fact_repo import FactRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.services.event_bus import EventBus
from capybara.services.memory_service import MemoryService
from support import StubMemoryAgent


@pytest_asyncio.fixture
async def user_id(engine: AsyncEngine, make_user):  # type: ignore[no-untyped-def]
    maker = create_sessionmaker(engine)
    async with maker() as s:
        user = await make_user(s, username="mem", display_name="Mem")
        await s.commit()
        return user.id


async def test_add_and_list_facts(engine: AsyncEngine, settings: Settings, user_id) -> None:  # type: ignore[no-untyped-def]
    maker = create_sessionmaker(engine)
    agent = StubMemoryAgent(settings, embeddings={"Любит горы": [1.0] + [0.0] * 767})
    service = MemoryService(maker, agent, settings)

    fact = await service.add_fact(user_id, "Любит горы", "personal")
    assert fact.source == "manual"

    facts = await service.list_facts(user_id)
    assert [f.content for f in facts] == ["Любит горы"]


async def test_recall_filters_by_min_similarity(
    engine: AsyncEngine, settings: Settings, user_id
) -> None:  # type: ignore[no-untyped-def]
    maker = create_sessionmaker(engine)
    near = [1.0] + [0.0] * 767
    far = [0.0, 1.0] + [0.0] * 766
    async with maker() as s:
        repo = FactRepo(s)
        await repo.create(
            user_id=user_id, category="personal", content="near", embedding=near, source="manual"
        )
        await repo.create(
            user_id=user_id, category="personal", content="far", embedding=far, source="manual"
        )
        await s.commit()

    # Query embedding == `near`; min_similarity 0.3 excludes the orthogonal `far` (sim 0).
    agent = StubMemoryAgent(settings, embeddings={"q": near})
    service = MemoryService(maker, agent, settings)
    facts = await service.recall(user_id, "q")
    assert [f.content for f in facts] == ["near"]


async def test_update_reembeds_only_on_content_change(
    engine: AsyncEngine, settings: Settings, user_id
) -> None:  # type: ignore[no-untyped-def]
    maker = create_sessionmaker(engine)
    v1 = [1.0] + [0.0] * 767
    v2 = [0.0, 1.0] + [0.0] * 766
    agent = StubMemoryAgent(settings, embeddings={"old": v1, "new": v2})
    service = MemoryService(maker, agent, settings)

    fact = await service.add_fact(user_id, "old", "personal")
    updated = await service.update_fact(user_id, fact.id, content="new")
    assert updated is not None and updated.content == "new"

    # Re-embedded: it is now nearest to v2, not v1.
    async with maker() as s:
        results = await FactRepo(s).search(user_id, v2, k=1)
    assert results and results[0][0].id == fact.id and results[0][1] < 0.01


async def test_delete_and_ownership_guard(engine: AsyncEngine, settings: Settings, user_id) -> None:  # type: ignore[no-untyped-def]
    from uuid import uuid4

    maker = create_sessionmaker(engine)
    agent = StubMemoryAgent(settings)
    service = MemoryService(maker, agent, settings)
    fact = await service.add_fact(user_id, "x", "personal")

    assert await service.delete_fact(uuid4(), fact.id) is False  # wrong owner → no-op
    assert await service.delete_fact(user_id, fact.id) is True
    assert await service.list_facts(user_id) == []


async def test_auto_capture_flag_roundtrip(
    engine: AsyncEngine, settings: Settings, user_id
) -> None:  # type: ignore[no-untyped-def]
    maker = create_sessionmaker(engine)
    service = MemoryService(maker, StubMemoryAgent(settings), settings)
    assert await service.get_auto_capture(user_id) is True
    assert await service.set_auto_capture(user_id, False) is False
    assert await service.get_auto_capture(user_id) is False


async def test_auto_capture_raises_lookup_error_for_missing_user(
    engine: AsyncEngine, settings: Settings
) -> None:
    """A vanished user surfaces as an explicit LookupError, not a stripped-out assert.

    An `assert` here would disappear under `python -O` and turn into an
    AttributeError on None; the failure must stay explicit on every interpreter.
    """
    from uuid import uuid4

    maker = create_sessionmaker(engine)
    service = MemoryService(maker, StubMemoryAgent(settings), settings)
    ghost = uuid4()
    with pytest.raises(LookupError):
        await service.get_auto_capture(ghost)
    with pytest.raises(LookupError):
        await service.set_auto_capture(ghost, True)


async def test_extract_and_store_publishes_and_persists(engine, settings, user_id) -> None:  # type: ignore[no-untyped-def]
    """A stored fact is written to the message's memory_saves AND published on the bus."""
    maker = create_sessionmaker(engine)
    agent = StubMemoryAgent(
        settings, extracted={"facts": [{"content": "Любит чай", "category": "preference"}]}
    )
    bus = EventBus()
    service = MemoryService(maker, agent, settings, bus)

    async with maker() as s:
        user = await s.get(User, user_id)
        assert user is not None
        user.memory_auto_capture = True
        chat = await ChatRepo(s).create(user_id, "c", "test-model")
        messages = MessageRepo(s)
        await messages.create(chat_id=chat.id, role="user", content="Привет")
        assistant = await messages.create(chat_id=chat.id, role="assistant", content="Здравствуй")
        await s.commit()
        chat_id, assistant_id = chat.id, assistant.id

    async with bus.subscribe(user_id) as queue:
        await service.extract_and_store(user_id, chat_id)
        event = await asyncio.wait_for(queue.get(), timeout=2)

    assert event["event"] == "memory-save"
    assert event["data"]["chat_id"] == str(chat_id)
    assert event["data"]["message_id"] == str(assistant_id)
    assert event["data"]["facts"] == [{"content": "Любит чай", "category": "preference"}]

    async with maker() as s:
        stored = await MessageRepo(s).get(assistant_id)
        assert stored is not None
        assert stored.memory_saves == [{"content": "Любит чай", "category": "preference"}]


async def test_extract_and_store_no_facts_publishes_nothing(engine, settings, user_id) -> None:  # type: ignore[no-untyped-def]
    """When extraction yields no facts, nothing is persisted or published."""
    maker = create_sessionmaker(engine)
    agent = StubMemoryAgent(settings, extracted={"facts": []})
    bus = EventBus()
    service = MemoryService(maker, agent, settings, bus)

    async with maker() as s:
        user = await s.get(User, user_id)
        assert user is not None
        user.memory_auto_capture = True
        chat = await ChatRepo(s).create(user_id, "c", "test-model")
        messages = MessageRepo(s)
        await messages.create(chat_id=chat.id, role="user", content="Привет")
        assistant = await messages.create(chat_id=chat.id, role="assistant", content="Здравствуй")
        await s.commit()
        chat_id, assistant_id = chat.id, assistant.id

    async with bus.subscribe(user_id) as queue:
        await service.extract_and_store(user_id, chat_id)
        assert queue.empty()

    async with maker() as s:
        stored = await MessageRepo(s).get(assistant_id)
        assert stored is not None
        assert stored.memory_saves is None
