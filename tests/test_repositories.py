from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from capybara.db.models import User
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.repositories.user_repo import UserRepo


async def _seed_user(session: AsyncSession) -> User:
    user = User(username="roman", display_name="Роман")
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
    listed = await chats.list_for_user(user.id)
    assert [c.id for c in listed] == [chat.id]


async def test_chat_repo_create_default_title(session: AsyncSession) -> None:
    user = await _seed_user(session)
    chat = await ChatRepo(session).create(user.id, None)
    assert chat.title == "Новый чат"


async def test_message_repo_add_and_order(session: AsyncSession) -> None:
    user = await _seed_user(session)
    chat = await ChatRepo(session).create(user.id, "c")
    messages = MessageRepo(session)
    await messages.add(chat.id, "user", "Привет")
    await messages.add(chat.id, "assistant", "Здравствуйте", model="test-model")
    ordered = await messages.list_for_chat(chat.id)
    assert [m.role for m in ordered] == ["user", "assistant"]
    assert ordered[1].model == "test-model"


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
    user_msg = await repo.add(chat.id, "user", "Hello")
    assistant_msg = await repo.add(chat.id, "assistant", "Hi there", model="m")

    # seq must be monotonically increasing regardless of created_at equality.
    assert user_msg.seq < assistant_msg.seq

    ordered = await repo.list_for_chat(chat.id)
    assert [m.role for m in ordered] == ["user", "assistant"]
