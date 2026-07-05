from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from capybara.db.models import Chat, Message, User
from capybara.filters import FieldEquals
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.repositories.user_repo import UserRepo
from capybara.security.passwords import hash_password


async def _seed_user(session: AsyncSession) -> User:
    user = User(
        username="roman",
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


async def test_chat_repo_create_list_get(session: AsyncSession) -> None:
    user = await _seed_user(session)
    chats = ChatRepo(session)
    chat = await chats.create(user.id, "Sales Q2")
    assert chat.title == "Sales Q2"
    assert (await chats.get(chat.id)).id == chat.id  # type: ignore[union-attr]
    listed = await chats.list(FieldEquals(Chat.user_id, user.id))
    assert [c.id for c in listed] == [chat.id]


async def test_chat_repo_create_default_title(session: AsyncSession) -> None:
    user = await _seed_user(session)
    chat = await ChatRepo(session).create(user.id, None)
    assert chat.title == "Новый чат"


async def test_message_repo_add_and_order(session: AsyncSession) -> None:
    user = await _seed_user(session)
    chat = await ChatRepo(session).create(user.id, "c")
    messages = MessageRepo(session)
    await messages.create(chat_id=chat.id, role="user", content="Привет")
    await messages.create(
        chat_id=chat.id, role="assistant", content="Здравствуйте", model="test-model"
    )
    ordered = await messages.list(FieldEquals(Message.chat_id, chat.id))
    assert [m.role for m in ordered] == ["user", "assistant"]
    assert ordered[1].model == "test-model"


async def test_base_repo_update_persists_field(session: AsyncSession) -> None:
    """update() with a valid mapped field changes the attribute and flushes."""
    user = await _seed_user(session)
    chats = ChatRepo(session)
    chat = await chats.create(user.id, "Original title")
    updated = await chats.update(chat, title="Renamed title")
    assert updated.title == "Renamed title"
    # Re-fetch from the session to confirm the change was flushed.
    refetched = await chats.get(chat.id)
    assert refetched is not None
    assert refetched.title == "Renamed title"


async def test_base_repo_update_rejects_unknown_field(session: AsyncSession) -> None:
    """update() with a non-mapped key raises ValueError instead of silently passing."""
    user = await _seed_user(session)
    chat = await ChatRepo(session).create(user.id, "Guard test")
    with pytest.raises(ValueError, match="Unknown field 'titel'"):
        await ChatRepo(session).update(chat, titel="typo")


async def test_message_repo_seq_ordering(session: AsyncSession) -> None:
    """Ordering relies on `seq` (identity column), not `created_at`.

    Both messages land in the same DB transaction so their `created_at`
    timestamps are identical (Postgres transaction timestamp).
    ORDER BY created_at would be non-deterministic; ORDER BY seq is always
    insertion-ordered.  This test would fail under the old code in two ways:
    1. `AttributeError` accessing `.seq` (column did not exist), AND
    2. the ORDER BY created_at produces undefined ordering for equal timestamps.
    """
    user = await _seed_user(session)
    chat = await ChatRepo(session).create(user.id, "seq-ordering-test")
    repo = MessageRepo(session)
    # Both inserts happen inside the same open transaction → same created_at.
    user_msg = await repo.create(chat_id=chat.id, role="user", content="Hello")
    assistant_msg = await repo.create(
        chat_id=chat.id, role="assistant", content="Hi there", model="m"
    )

    # seq must be monotonically increasing regardless of created_at equality.
    assert user_msg.seq < assistant_msg.seq

    ordered = await repo.list(FieldEquals(Message.chat_id, chat.id))
    assert [m.role for m in ordered] == ["user", "assistant"]


async def test_user_repo_list_orders_by_created_at_asc(session: AsyncSession) -> None:
    """UserRepo.list() returns users ordered by created_at ascending."""
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

    users = await UserRepo(session).list()
    usernames = [u.username for u in users]
    idx_older = usernames.index("aaa_older")
    idx_newer = usernames.index("bbb_newer")
    assert idx_older < idx_newer, "older created_at user must appear before newer"


async def test_chat_repo_create_persists_model(session) -> None:  # type: ignore[no-untyped-def]
    """A chat created with a model round-trips the model value."""
    from capybara.db.models import User
    from capybara.repositories.chat_repo import ChatRepo
    from capybara.security.passwords import hash_password

    user = User(username="modeluser", display_name="M", password_hash=hash_password("password123"))
    session.add(user)
    await session.flush()

    repo = ChatRepo(session)
    chat = await repo.create(user.id, title="c", model="llama3.1:8b")
    assert chat.model == "llama3.1:8b"

    reloaded = await repo.get(chat.id)
    assert reloaded is not None
    assert reloaded.model == "llama3.1:8b"


async def test_chat_repo_toggle_favorite(session) -> None:  # type: ignore[no-untyped-def]
    """A chat defaults to not-favorite and can be flipped via update."""
    from capybara.db.models import User
    from capybara.repositories.chat_repo import ChatRepo
    from capybara.security.passwords import hash_password

    user = User(username="favuser", display_name="F", password_hash=hash_password("password123"))
    session.add(user)
    await session.flush()

    repo = ChatRepo(session)
    chat = await repo.create(user.id, title="c")
    assert chat.is_favorite is False

    await repo.update(chat, is_favorite=True)
    reloaded = await repo.get(chat.id)
    assert reloaded is not None
    assert reloaded.is_favorite is True


async def test_field_equals_scopes_correctly(session: AsyncSession) -> None:
    """list(FieldEquals(...)) returns only rows matching the filter value."""
    user = await _seed_user(session)
    chat1 = await ChatRepo(session).create(user.id, "Chat 1")
    chat2 = await ChatRepo(session).create(user.id, "Chat 2")
    msgs = MessageRepo(session)
    await msgs.create(chat_id=chat1.id, role="user", content="in chat1")
    await msgs.create(chat_id=chat2.id, role="user", content="in chat2")

    result = await msgs.list(FieldEquals(Message.chat_id, chat1.id))
    assert len(result) == 1
    assert result[0].content == "in chat1"


async def test_fact_repo_search_returns_nearest_first(session: AsyncSession) -> None:
    from capybara.repositories.fact_repo import FactRepo

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
    from capybara.db.models import User
    from capybara.repositories.fact_repo import FactRepo
    from capybara.security.passwords import hash_password

    user_a = await _seed_user(session)
    user_b = User(username="userb", display_name="B", password_hash=hash_password("password123"))
    session.add(user_b)
    await session.flush()

    vec = [1.0] + [0.0] * 767
    repo = FactRepo(session)
    await repo.create(
        user_id=user_b.id, category="personal", content="b-secret", embedding=vec, source="manual"
    )

    results = await repo.search(user_a.id, vec, k=5)
    assert results == []
