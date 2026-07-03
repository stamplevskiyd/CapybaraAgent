from sqlalchemy.ext.asyncio import AsyncSession

from capybara.config import Settings
from capybara.db.models import User
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.filters import FieldEquals
from capybara.repositories.message_repo import MessageRepo
from capybara.services.chat_service import ChatService
from capybara.services.events import Delta, Done
from support import FakeAgent


async def test_stream_turn_streams_and_persists(
    session: AsyncSession, settings: Settings
) -> None:
    user = User(username="roman", display_name="Роман")
    session.add(user)
    await session.flush()
    chats, messages = ChatRepo(session), MessageRepo(session)
    chat = await chats.create(user.id, "c")

    service = ChatService(chats, messages, FakeAgent(settings, "Ответ"))

    events = [e async for e in service.stream_turn(chat.id, "Вопрос")]

    deltas = [e for e in events if isinstance(e, Delta)]
    done = [e for e in events if isinstance(e, Done)]
    assert "".join(d.text for d in deltas) == "Ответ"
    assert len(done) == 1

    stored = await messages.list(FieldEquals("chat_id", chat.id))
    assert [m.role for m in stored] == ["user", "assistant"]
    assert stored[1].content == "Ответ"
    assert stored[1].incomplete is False


async def test_stream_turn_disconnect_saves_partial(
    session: AsyncSession, settings: Settings
) -> None:
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

    service = ChatService(
        chats, messages, FakeAgent(settings, "Частичный ответ")
    )

    # Patch stream_reply on the agent instance so that it yields one partial
    # delta and then raises, reproducing an abrupt mid-stream abort.
    async def _abort_after_first(user_content, history, acc):  # type: ignore[no-untyped-def]
        acc.text += "Частич"
        yield "Частич"
        raise RuntimeError("simulated disconnect")

    original = service._agent.stream_reply  # type: ignore[method-assign]
    service._agent.stream_reply = _abort_after_first  # type: ignore[method-assign]
    try:
        events = []
        try:
            async for e in service.stream_turn(chat.id, "Вопрос"):
                events.append(e)
        except RuntimeError:
            pass  # expected – propagates from stream_reply through stream_turn
    finally:
        service._agent.stream_reply = original  # type: ignore[method-assign]

    assert events == [Delta(text="Частич")]  # exactly one Delta, no Done
    stored = await messages.list(FieldEquals("chat_id", chat.id))
    assert stored[-1].role == "assistant"
    assert stored[-1].incomplete is True
