"""Tests for ChatPrefService against real Postgres."""

from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.services.chat_pref_service import ChatPrefService

pytestmark = pytest.mark.asyncio


def _maker(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    """A sessionmaker that always hands back the test's transactional session."""

    class _Maker:
        def __call__(self):  # type: ignore[no-untyped-def]
            @asynccontextmanager
            async def _cm():  # type: ignore[no-untyped-def]
                yield session

            return _cm()

    return _Maker()  # type: ignore[return-value]


async def test_upsert_creates_then_updates_a_pref(
    session: AsyncSession,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """upsert creates a pref on first call and patches it in place on the next."""
    user = await make_user(session)
    await session.commit()
    service = ChatPrefService(_maker(session))
    thread_id = uuid4()

    created = await service.upsert(user.id, thread_id, is_favorite=True, model="llama3.1")
    assert created.is_favorite is True
    assert created.model == "llama3.1"

    updated = await service.upsert(user.id, thread_id, is_favorite=False, model=None)
    assert updated.id == created.id  # same row, patched
    assert updated.is_favorite is False
    assert updated.model is None

    prefs = await service.list_prefs(user.id)
    assert [p.thread_id for p in prefs] == [thread_id]


async def test_prefs_are_scoped_to_the_owner(
    session: AsyncSession,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """A user only sees their own prefs; another user's thread pref is invisible."""
    owner = await make_user(session, username="owner")
    other = await make_user(session, username="other")
    await session.commit()
    service = ChatPrefService(_maker(session))
    thread_id = uuid4()
    await service.upsert(owner.id, thread_id, is_favorite=True, model=None)

    assert await service.list_prefs(other.id) == []


async def test_delete_removes_a_pref(
    session: AsyncSession,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """delete removes the pref and reports whether it existed."""
    user = await make_user(session)
    await session.commit()
    service = ChatPrefService(_maker(session))
    thread_id = uuid4()
    await service.upsert(user.id, thread_id, is_favorite=True, model=None)

    assert await service.delete(user.id, thread_id) is True
    assert await service.list_prefs(user.id) == []
    assert await service.delete(user.id, thread_id) is False  # already gone
