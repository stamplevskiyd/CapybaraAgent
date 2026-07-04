from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from capybara.config import Settings
from capybara.db.engine import create_sessionmaker
from capybara.db.models import Chat, Message
from capybara.filters import FieldEquals
from capybara.repositories.message_repo import MessageRepo
from capybara.services.chat_service import ChatNotFoundError, ChatService
from capybara.services.events import Delta, Done
from support import FakeAgent, PartialThenFailAgent, RaisingAgent


async def _seed_chat(engine: AsyncEngine, make_user, username: str) -> tuple[object, object]:  # type: ignore[no-untyped-def]
    """Persist a user and an empty chat; return (user_id, chat_id) both committed."""
    maker = create_sessionmaker(engine)
    async with maker() as setup:
        user = await make_user(setup, username=username, display_name=username)
        chat = Chat(user_id=user.id, title="c")
        setup.add(chat)
        await setup.commit()
        return user.id, chat.id


async def test_stream_turn_streams_and_persists(
    engine: AsyncEngine,
    settings: Settings,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    user_id, chat_id = await _seed_chat(engine, make_user, "roman")
    maker = create_sessionmaker(engine)

    service = ChatService(maker, FakeAgent(settings, "Ответ"))

    history = await service.begin_turn(user_id, chat_id, "Вопрос")  # type: ignore[arg-type]
    events = [e async for e in service.stream_turn(chat_id, "Вопрос", history)]  # type: ignore[arg-type]

    deltas = [e for e in events if isinstance(e, Delta)]
    done = [e for e in events if isinstance(e, Done)]
    assert "".join(d.text for d in deltas) == "Ответ"
    assert len(done) == 1

    async with maker() as check:
        stored = await MessageRepo(check).list(FieldEquals(Message.chat_id, chat_id))
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
    user_id, chat_id = await _seed_chat(engine, make_user, "err_user")
    maker = create_sessionmaker(engine)

    service = ChatService(maker, PartialThenFailAgent(settings, "Частич", "boom"))

    history = await service.begin_turn(user_id, chat_id, "Вопрос")  # type: ignore[arg-type]
    events = []
    with pytest.raises(RuntimeError):
        async for e in service.stream_turn(chat_id, "Вопрос", history):  # type: ignore[arg-type]
            events.append(e)

    assert events == [Delta(text="Частич")]  # exactly one delta, no Done

    async with maker() as check:
        stored = await MessageRepo(check).list(FieldEquals(Message.chat_id, chat_id))
    assert [m.role for m in stored] == ["user", "assistant"]
    assert stored[-1].incomplete is True
    assert stored[-1].content == "Частич"


async def test_stream_turn_does_not_persist_empty_assistant_on_immediate_error(
    engine: AsyncEngine,
    settings: Settings,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """An LLM error before the first token leaves no blank assistant message behind.

    Otherwise the empty row would re-enter the model context as history on the next turn.
    Only the already-saved user message should remain.
    """
    user_id, chat_id = await _seed_chat(engine, make_user, "empty_user")
    maker = create_sessionmaker(engine)

    service = ChatService(maker, RaisingAgent(settings, "boom"))

    history = await service.begin_turn(user_id, chat_id, "Вопрос")  # type: ignore[arg-type]
    with pytest.raises(RuntimeError):
        async for _ in service.stream_turn(chat_id, "Вопрос", history):  # type: ignore[arg-type]
            pass

    async with maker() as check:
        stored = await MessageRepo(check).list(FieldEquals(Message.chat_id, chat_id))
    assert [m.role for m in stored] == ["user"]


async def test_begin_turn_rejects_missing_chat(
    engine: AsyncEngine,
    settings: Settings,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """A non-existent chat raises before any message is written."""
    user_id, _ = await _seed_chat(engine, make_user, "ghost_user")
    maker = create_sessionmaker(engine)
    service = ChatService(maker, FakeAgent(settings, "x"))

    with pytest.raises(ChatNotFoundError):
        await service.begin_turn(user_id, uuid4(), "Вопрос")  # type: ignore[arg-type]


async def test_begin_turn_rejects_foreign_chat(
    engine: AsyncEngine,
    settings: Settings,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """A chat owned by another user is treated as not found, and nothing is written."""
    _, chat_id = await _seed_chat(engine, make_user, "owner_user")
    other_id, _ = await _seed_chat(engine, make_user, "intruder_user")
    maker = create_sessionmaker(engine)
    service = ChatService(maker, FakeAgent(settings, "x"))

    with pytest.raises(ChatNotFoundError):
        await service.begin_turn(other_id, chat_id, "Вопрос")  # type: ignore[arg-type]

    async with maker() as check:
        stored = await MessageRepo(check).list(FieldEquals(Message.chat_id, chat_id))
    assert stored == []
