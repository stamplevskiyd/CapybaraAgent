from datetime import UTC, datetime, timedelta
from typing import ClassVar
from uuid import uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from capybara.db.models import Fact, User
from capybara.filters import FieldEquals, Filter
from capybara.repositories.fact_repo import FactRepo
from capybara.repositories.user_repo import UserRepo
from capybara.security.passwords import hash_password


async def _seed_user(session: AsyncSession, username: str = "roman") -> User:
    user = User(
        username=username,
        display_name="Роман",
        password_hash=hash_password("password123"),
    )
    session.add(user)
    await session.flush()
    return user


async def test_user_repo_get(session: AsyncSession) -> None:
    user = await _seed_user(session)
    fetched = await UserRepo(session).get(user.id)
    assert fetched is not None and fetched.username == "roman"
    assert await UserRepo(session).get(uuid4()) is None


async def test_get_one_by_field(session: AsyncSession) -> None:
    """get_one returns the single match by an arbitrary filter, or None."""
    await _seed_user(session, username="alpha")
    repo = UserRepo(session)
    found = await repo.get_one(FieldEquals(User.username, "alpha"))
    assert found is not None and found.username == "alpha"
    assert await repo.get_one(FieldEquals(User.username, "ghost")) is None


async def test_base_repo_update_persists_field(session: AsyncSession) -> None:
    """update() with a valid mapped field changes the attribute and flushes."""
    user = await _seed_user(session)
    repo = UserRepo(session)
    updated = await repo.update(user, display_name="Renamed")
    assert updated.display_name == "Renamed"
    # Re-fetch from the session to confirm the change was flushed.
    refetched = await repo.get(user.id)
    assert refetched is not None
    assert refetched.display_name == "Renamed"


async def test_base_repo_update_accepts_pydantic_payload(session: AsyncSession) -> None:
    """update() unpacks a pydantic model's set fields; explicit kwargs override it."""

    class UserPatch(BaseModel):
        display_name: str | None = None

    user = await _seed_user(session)
    repo = UserRepo(session)
    updated = await repo.update(user, data=UserPatch(display_name="From payload"))
    assert updated.display_name == "From payload"

    # Unset payload fields are not applied — display_name stays as-is.
    updated = await repo.update(user, data=UserPatch())
    assert updated.display_name == "From payload"


async def test_base_repo_update_rejects_unknown_field(session: AsyncSession) -> None:
    """update() with a non-mapped key raises ValueError instead of silently passing."""
    user = await _seed_user(session)
    with pytest.raises(ValueError, match="Unknown field 'display_nam'"):
        await UserRepo(session).update(user, display_nam="typo")


async def test_default_filters_apply_and_can_be_bypassed(session: AsyncSession) -> None:
    """default_filters scope every read; bypass_default_filters=True lifts them."""

    class ManualFactRepo(FactRepo):
        default_filters: ClassVar[tuple[Filter, ...]] = (FieldEquals(Fact.source, "manual"),)

    user = await _seed_user(session)
    repo = ManualFactRepo(session)
    vec = [1.0] + [0.0] * 767
    await repo.create(
        user_id=user.id, category="personal", content="manual", embedding=vec, source="manual"
    )
    await repo.create(
        user_id=user.id, category="personal", content="auto", embedding=vec, source="auto"
    )

    scoped = await repo.get_list(FieldEquals(Fact.user_id, user.id))
    assert [f.content for f in scoped] == ["manual"]

    everything = await repo.get_list(
        FieldEquals(Fact.user_id, user.id), bypass_default_filters=True
    )
    assert {f.content for f in everything} == {"manual", "auto"}


async def test_user_repo_list_orders_by_created_at_asc(session: AsyncSession) -> None:
    """UserRepo.get_list() returns users ordered by created_at ascending."""
    now = datetime.now(UTC)
    older = User(
        username="aaa_older",
        display_name="Older",
        created_at=now - timedelta(hours=1),
        updated_at=now,
        password_hash=hash_password("x"),
    )
    newer = User(
        username="bbb_newer",
        display_name="Newer",
        created_at=now,
        updated_at=now,
        password_hash=hash_password("x"),
    )
    session.add_all([older, newer])
    await session.flush()

    users = await UserRepo(session).get_list()
    usernames = [u.username for u in users]
    idx_older = usernames.index("aaa_older")
    idx_newer = usernames.index("bbb_newer")
    assert idx_older < idx_newer, "older created_at user must appear before newer"


async def test_get_list_filter_scopes_correctly(session: AsyncSession) -> None:
    """get_list(FieldEquals(...)) returns only rows matching the filter value."""
    user_a = await _seed_user(session)
    user_b = await _seed_user(session, username="userb")
    vec = [1.0] + [0.0] * 767
    repo = FactRepo(session)
    await repo.create(
        user_id=user_a.id, category="personal", content="a-fact", embedding=vec, source="manual"
    )
    await repo.create(
        user_id=user_b.id, category="personal", content="b-fact", embedding=vec, source="manual"
    )

    result = await repo.get_list(FieldEquals(Fact.user_id, user_a.id))
    assert [f.content for f in result] == ["a-fact"]


async def test_fact_repo_search_returns_nearest_first(session: AsyncSession) -> None:
    user = await _seed_user(session)
    repo = FactRepo(session)
    # Three orthogonal-ish unit vectors in 768-space.
    near = [1.0] + [0.0] * 767
    mid = [0.6, 0.8] + [0.0] * 766
    far = [0.0, 1.0] + [0.0] * 766
    await repo.create(
        user_id=user.id, category="personal", content="near", embedding=near, source="manual"
    )
    await repo.create(
        user_id=user.id, category="personal", content="mid", embedding=mid, source="manual"
    )
    await repo.create(
        user_id=user.id, category="personal", content="far", embedding=far, source="manual"
    )

    results = await repo.search(user.id, near, k=3)
    assert [fact.content for fact, _distance in results] == ["near", "mid", "far"]
    assert results[0][1] < results[-1][1]  # nearest has the smallest distance


async def test_fact_repo_search_is_user_scoped(session: AsyncSession) -> None:
    user_a = await _seed_user(session)
    user_b = await _seed_user(session, username="userb")

    vec = [1.0] + [0.0] * 767
    repo = FactRepo(session)
    await repo.create(
        user_id=user_b.id, category="personal", content="b-secret", embedding=vec, source="manual"
    )

    results = await repo.search(user_a.id, vec, k=5)
    assert results == []
