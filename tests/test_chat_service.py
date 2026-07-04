import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from capybara.config import Settings
from capybara.db.engine import create_sessionmaker
from capybara.db.models import Chat
from capybara.filters import FieldEquals
from capybara.repositories.message_repo import MessageRepo
from capybara.services.chat_service import ChatService
from capybara.services.events import Delta, Done
from support import FakeAgent, PartialThenFailAgent


async def _seed_chat(engine: AsyncEngine, make_user, username: str) -> object:  # type: ignore[no-untyped-def]
    """Persist a user and an empty chat, committed so short-lived sessions can see them."""
    maker = create_sessionmaker(engine)
    async with maker() as setup:
        user = await make_user(setup, username=username, display_name=username)
        chat = Chat(user_id=user.id, title="c")
        setup.add(chat)
        await setup.commit()
        return chat.id


async def test_stream_turn_streams_and_persists(
    engine: AsyncEngine,
    settings: Settings,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    chat_id = await _seed_chat(engine, make_user, "roman")
    maker = create_sessionmaker(engine)

    service = ChatService(maker, FakeAgent(settings, "Ответ"))

    events = [e async for e in service.stream_turn(chat_id, "Вопрос")]  # type: ignore[arg-type]

    deltas = [e for e in events if isinstance(e, Delta)]
    done = [e for e in events if isinstance(e, Done)]
    assert "".join(d.text for d in deltas) == "Ответ"
    assert len(done) == 1

    async with maker() as check:
        stored = await MessageRepo(check).list(FieldEquals("chat_id", chat_id))
    assert [m.role for m in stored] == ["user", "assistant"]
    assert stored[1].content == "Ответ"
    assert stored[1].incomplete is False


async def test_stream_turn_persists_partial_on_stream_error(
    engine: AsyncEngine,
    settings: Settings,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """When the stream fails mid-reply, the partial assistant text is saved as incomplete.

    This is the real failure mode behind ``incomplete=True``: an LLM/transport error
    after some tokens have been streamed.  The user message must already be persisted,
    and the partial assistant message recorded with ``incomplete=True``, before the
    error propagates to the caller.
    """
    chat_id = await _seed_chat(engine, make_user, "err_user")
    maker = create_sessionmaker(engine)

    service = ChatService(maker, PartialThenFailAgent(settings, "Частич", "boom"))

    events = []
    with pytest.raises(RuntimeError):
        async for e in service.stream_turn(chat_id, "Вопрос"):  # type: ignore[arg-type]
            events.append(e)

    assert events == [Delta(text="Частич")]  # exactly one delta, no Done

    async with maker() as check:
        stored = await MessageRepo(check).list(FieldEquals("chat_id", chat_id))
    assert [m.role for m in stored] == ["user", "assistant"]
    assert stored[-1].incomplete is True
    assert stored[-1].content == "Частич"
