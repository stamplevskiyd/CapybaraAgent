"""Tests for the fact commands against real Postgres."""

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine

from capybara.api.schemas import FactUpdate
from capybara.commands.fact.create import CreateFact
from capybara.commands.fact.delete import DeleteFact
from capybara.commands.fact.list import ListFacts
from capybara.commands.fact.recall import RecallFacts
from capybara.commands.fact.update import UpdateFact
from capybara.config import Settings
from capybara.db.engine import create_sessionmaker
from capybara.repositories.fact_repo import FactRepo
from support import StubMemoryAgent


@pytest_asyncio.fixture
async def user_id(engine: AsyncEngine, make_user):  # type: ignore[no-untyped-def]
    maker = create_sessionmaker(engine)
    async with maker() as s:
        user = await make_user(s, username="mem", display_name="Mem")
        await s.commit()
        return user.id


async def test_create_and_list_facts(engine: AsyncEngine, settings: Settings, user_id) -> None:  # type: ignore[no-untyped-def]
    maker = create_sessionmaker(engine)
    agent = StubMemoryAgent(settings, embeddings={"Любит горы": [1.0] + [0.0] * 767})

    fact = await CreateFact(
        maker, agent, user_id=user_id, content="Любит горы", category="personal"
    ).execute()
    assert fact.source == "manual"

    facts = await ListFacts(maker, user_id=user_id).execute()
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
    facts = await RecallFacts(maker, agent, settings, user_id=user_id, query="q").execute()
    assert [f.content for f in facts] == ["near"]


async def test_update_reembeds_new_content(
    engine: AsyncEngine, settings: Settings, user_id
) -> None:  # type: ignore[no-untyped-def]
    maker = create_sessionmaker(engine)
    v1 = [1.0] + [0.0] * 767
    v2 = [0.0, 1.0] + [0.0] * 766
    agent = StubMemoryAgent(settings, embeddings={"old": v1, "new": v2})

    fact = await CreateFact(
        maker, agent, user_id=user_id, content="old", category="personal"
    ).execute()
    updated = await UpdateFact(
        maker, agent, user_id=user_id, fact_id=fact.id, patch=FactUpdate(content="new")
    ).execute()
    assert updated is not None and updated.content == "new"

    # Re-embedded: it is now nearest to v2, not v1.
    async with maker() as s:
        results = await FactRepo(s).search(user_id, v2, k=1)
    assert results and results[0][0].id == fact.id and results[0][1] < 0.01


async def test_delete_and_ownership_guard(engine: AsyncEngine, settings: Settings, user_id) -> None:  # type: ignore[no-untyped-def]
    from uuid import uuid4

    maker = create_sessionmaker(engine)
    agent = StubMemoryAgent(settings)
    fact = await CreateFact(
        maker, agent, user_id=user_id, content="x", category="personal"
    ).execute()

    # wrong owner → no-op
    assert await DeleteFact(maker, user_id=uuid4(), fact_id=fact.id).execute() is False
    assert await DeleteFact(maker, user_id=user_id, fact_id=fact.id).execute() is True
    assert await ListFacts(maker, user_id=user_id).execute() == []
