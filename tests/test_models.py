from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from capybara.db.models import Chat, Message


async def test_insert_and_read_graph(session: AsyncSession, make_user) -> None:  # type: ignore[no-untyped-def]
    user = await make_user(session, username="roman", display_name="Роман")

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


async def test_fact_model_persists_with_embedding(session: AsyncSession) -> None:
    from capybara.db.models import Fact, User
    from capybara.security.passwords import hash_password

    user = User(username="factuser", display_name="F", password_hash=hash_password("password123"))
    session.add(user)
    await session.flush()

    fact = Fact(
        user_id=user.id,
        category="personal",
        content="Пьёт чай без сахара",
        embedding=[0.1] * 768,
        source="manual",
    )
    session.add(fact)
    await session.flush()

    assert fact.id is not None
    assert fact.created_at is not None
    assert user.memory_auto_capture is True
