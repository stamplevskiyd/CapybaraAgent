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
