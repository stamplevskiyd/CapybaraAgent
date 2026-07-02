from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from capybara.db.models import Chat, Message, User


async def test_insert_and_read_graph(session: AsyncSession) -> None:
    user = User(username="roman", display_name="Роман")
    session.add(user)
    await session.flush()

    chat = Chat(user_id=user.id, title="First chat")
    session.add(chat)
    await session.flush()

    msg = Message(chat_id=chat.id, role="user", content="Привет")
    session.add(msg)
    await session.flush()

    loaded = (await session.execute(select(Message).where(Message.chat_id == chat.id))).scalar_one()
    assert loaded.role == "user"
    assert loaded.content == "Привет"
    assert loaded.incomplete is False
    assert loaded.model is None
    assert isinstance(user.id, type(uuid4()))
