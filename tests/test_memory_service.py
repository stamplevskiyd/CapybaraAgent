import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine

from capybara.config import Settings
from capybara.db.engine import create_sessionmaker
from capybara.repositories.fact_repo import FactRepo
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
