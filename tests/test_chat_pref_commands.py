"""Tests for the chat-pref commands against real Postgres."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.commands.chat_pref.delete import DeleteChatPref
from capybara.commands.chat_pref.get import GetChatPref
from capybara.commands.chat_pref.list import ListChatPrefs
from capybara.commands.chat_pref.upsert import UpsertChatPref

pytestmark = pytest.mark.asyncio


def _maker(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    """A sessionmaker that always hands back the test's transactional session."""
    from contextlib import asynccontextmanager

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
    """UpsertChatPref creates a pref on first call and patches it in place on the next."""
    user = await make_user(session)
    await session.commit()
    maker = _maker(session)
    thread_id = uuid4()

    created = await UpsertChatPref(
        maker, user_id=user.id, thread_id=thread_id, is_favorite=True, model="llama3.1", mode="fast"
    ).execute()
    assert created.is_favorite is True
    assert created.model == "llama3.1"

    updated = await UpsertChatPref(
        maker, user_id=user.id, thread_id=thread_id, is_favorite=False, model=None, mode="fast"
    ).execute()
    assert updated.id == created.id  # same row, patched
    assert updated.is_favorite is False
    assert updated.model is None

    prefs = await ListChatPrefs(maker, user_id=user.id).execute()
    assert [p.thread_id for p in prefs] == [thread_id]


async def test_prefs_are_scoped_to_the_owner(
    session: AsyncSession,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """A user only sees their own prefs; another user's thread pref is invisible."""
    owner = await make_user(session, username="owner")
    other = await make_user(session, username="other")
    await session.commit()
    maker = _maker(session)
    thread_id = uuid4()
    await UpsertChatPref(
        maker, user_id=owner.id, thread_id=thread_id, is_favorite=True, model=None, mode="fast"
    ).execute()

    assert await ListChatPrefs(maker, user_id=other.id).execute() == []
    assert await GetChatPref(maker, user_id=other.id, thread_id=thread_id).execute() is None
    got = await GetChatPref(maker, user_id=owner.id, thread_id=thread_id).execute()
    assert got is not None and got.is_favorite is True


async def test_upsert_persists_mode(
    session: AsyncSession,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """UpsertChatPref writes the agent mode and updates it in place."""
    user = await make_user(session)
    await session.commit()
    maker = _maker(session)
    thread_id = uuid4()

    created = await UpsertChatPref(
        maker, user_id=user.id, thread_id=thread_id, is_favorite=False, model=None, mode="smart"
    ).execute()
    assert created.mode == "smart"

    updated = await UpsertChatPref(
        maker, user_id=user.id, thread_id=thread_id, is_favorite=False, model=None, mode="fast"
    ).execute()
    assert updated.id == created.id and updated.mode == "fast"


async def test_delete_removes_a_pref(
    session: AsyncSession,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """DeleteChatPref removes the pref and reports whether it existed."""
    user = await make_user(session)
    await session.commit()
    maker = _maker(session)
    thread_id = uuid4()
    await UpsertChatPref(
        maker, user_id=user.id, thread_id=thread_id, is_favorite=True, model=None, mode="fast"
    ).execute()

    assert await DeleteChatPref(maker, user_id=user.id, thread_id=thread_id).execute() is True
    assert await ListChatPrefs(maker, user_id=user.id).execute() == []
    # already gone
    assert await DeleteChatPref(maker, user_id=user.id, thread_id=thread_id).execute() is False
