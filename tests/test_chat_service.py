from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import AsyncSession

import capybara.services.chat_service as _svc_module
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


async def test_stream_turn_disconnect_saves_partial(session: AsyncSession) -> None:
    """Simulates a client disconnect mid-stream and verifies the partial assistant
    message is persisted with incomplete=True.

    Why not aclose(): calling aclose() on stream_turn throws GeneratorExit into
    the generator while pydantic-ai's agent is still live.  pydantic-ai uses anyio
    internally; anyio wraps the athrow in a cancel scope that then cancels the
    SQLAlchemy session flush inside our finally block, so the DB write never
    completes.  The identical code path (finally with completed=False) is reached
    when stream_reply itself raises an exception mid-stream, which is what actually
    happens on a real disconnect (the transport raises at the next send/recv).  We
    therefore patch stream_reply to raise after yielding one partial delta.
    """
    user = User(username="disconnect_user", display_name="Disconnect User")
    session.add(user)
    await session.flush()
    chats, messages = ChatRepo(session), MessageRepo(session)
    chat = await chats.create(user.id, "dc")

    agent: Agent[None, str] = Agent(TestModel(custom_output_text="Частичный ответ"))
    service = ChatService(chats, messages, agent)

    # Patch stream_reply in the chat_service module namespace so that it yields
    # one partial delta and then raises, reproducing an abrupt mid-stream abort.
    async def _abort_after_first(the_agent, user_content, history, acc):
        acc.text += "Частич"
        yield "Частич"
        raise RuntimeError("simulated disconnect")

    original = _svc_module.stream_reply
    _svc_module.stream_reply = _abort_after_first
    try:
        events = []
        try:
            async for e in service.stream_turn(chat.id, "Вопрос"):
                events.append(e)
        except RuntimeError:
            pass  # expected – propagates from stream_reply through stream_turn
    finally:
        _svc_module.stream_reply = original

    assert events == [Delta(text="Частич")]  # exactly one Delta, no Done
    stored = await messages.list_for_chat(chat.id)
    assert stored[-1].role == "assistant"
    assert stored[-1].incomplete is True
