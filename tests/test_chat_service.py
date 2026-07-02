from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import AsyncSession

from capybara.db.models import User
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.services.chat_service import ChatService
from capybara.services.events import Delta, Done


async def test_stream_turn_streams_and_persists(session: AsyncSession) -> None:
    user = User(username="roman", display_name="Роман")
    session.add(user)
    await session.flush()
    chats, messages = ChatRepo(session), MessageRepo(session)
    chat = await chats.create(user.id, "c")

    agent: Agent[None, str] = Agent(TestModel(custom_output_text="Ответ"))
    service = ChatService(chats, messages, agent)

    events = [e async for e in service.stream_turn(chat.id, "Вопрос")]

    deltas = [e for e in events if isinstance(e, Delta)]
    done = [e for e in events if isinstance(e, Done)]
    assert "".join(d.text for d in deltas) == "Ответ"
    assert len(done) == 1

    stored = await messages.list_for_chat(chat.id)
    assert [m.role for m in stored] == ["user", "assistant"]
    assert stored[1].content == "Ответ"
    assert stored[1].incomplete is False
