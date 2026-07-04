from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from capybara.config import Settings
from capybara.db.engine import create_sessionmaker
from capybara.db.models import Chat, Message
from capybara.filters import FieldEquals
from capybara.repositories.message_repo import MessageRepo
from capybara.services.chat_service import ChatNotFoundError, ChatService, NoUserMessageError
from capybara.services.events import Delta, Done
from support import FakeAgent, PartialThenFailAgent, RaisingAgent


async def _seed_chat(engine: AsyncEngine, make_user, username: str) -> tuple[object, object]:  # type: ignore[no-untyped-def]
    """Persist a user and an empty chat; return (user_id, chat_id) both committed."""
    maker = create_sessionmaker(engine)
    async with maker() as setup:
        user = await make_user(setup, username=username, display_name=username)
        chat = Chat(user_id=user.id, title="c", model="test-model")
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

    model, history = await service.begin_turn(user_id, chat_id, "Вопрос")  # type: ignore[arg-type]
    events = [e async for e in service.stream_turn(chat_id, model, "Вопрос", history)]  # type: ignore[arg-type]

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

    model, history = await service.begin_turn(user_id, chat_id, "Вопрос")  # type: ignore[arg-type]
    events = []
    with pytest.raises(RuntimeError):
        async for e in service.stream_turn(chat_id, model, "Вопрос", history):  # type: ignore[arg-type]
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

    model, history = await service.begin_turn(user_id, chat_id, "Вопрос")  # type: ignore[arg-type]
    with pytest.raises(RuntimeError):
        async for _ in service.stream_turn(chat_id, model, "Вопрос", history):  # type: ignore[arg-type]
            pass

    async with maker() as check:
        stored = await MessageRepo(check).list(FieldEquals(Message.chat_id, chat_id))
    assert [m.role for m in stored] == ["user"]


async def test_begin_turn_excludes_incomplete_from_history(
    engine: AsyncEngine,
    settings: Settings,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """Incomplete assistant replies stay in the DB but are never replayed to the model.

    A half-streamed answer that failed mid-reply must not re-enter the model context as
    if it were a complete turn; it remains stored only for the UI to render.
    """
    from pydantic_ai.messages import ModelResponse, TextPart

    user_id, chat_id = await _seed_chat(engine, make_user, "hist_user")
    maker = create_sessionmaker(engine)
    async with maker() as setup:
        repo = MessageRepo(setup)
        await repo.create(chat_id=chat_id, role="user", content="q1")
        await repo.create(chat_id=chat_id, role="assistant", content="a1", incomplete=False)
        await repo.create(chat_id=chat_id, role="assistant", content="partial", incomplete=True)
        await setup.commit()

    service = ChatService(maker, FakeAgent(settings, "x"))
    _, history = await service.begin_turn(user_id, chat_id, "q2")  # type: ignore[arg-type]

    reply_texts = [
        part.content
        for message in history
        if isinstance(message, ModelResponse)
        for part in message.parts
        if isinstance(part, TextPart)
    ]
    assert "a1" in reply_texts
    assert "partial" not in reply_texts


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


async def test_begin_turn_rejects_model_not_installed(
    engine: AsyncEngine,
    settings: Settings,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """A chat whose model is not in the agent's live list is rejected before any write."""
    from capybara.agent import ModelUnavailableError

    maker = create_sessionmaker(engine)
    async with maker() as setup:
        user = await make_user(setup, username="badmodel", display_name="B")
        chat = Chat(user_id=user.id, title="c", model="ghost:1b")
        setup.add(chat)
        await setup.commit()
        user_id, chat_id = user.id, chat.id

    # FakeAgent only offers "test-model", so "ghost:1b" is unavailable.
    service = ChatService(maker, FakeAgent(settings, "x"))
    with pytest.raises(ModelUnavailableError):
        await service.begin_turn(user_id, chat_id, "Вопрос")  # type: ignore[arg-type]

    async with maker() as check:
        stored = await MessageRepo(check).list(FieldEquals(Message.chat_id, chat_id))
    assert stored == []  # user message must NOT be written when the model is invalid


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


# ---------------------------------------------------------------------------
# regenerate_turn tests
# ---------------------------------------------------------------------------


async def test_regenerate_turn_deletes_trailing_assistant_and_regenerates(
    engine: AsyncEngine,
    settings: Settings,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """regenerate_turn removes the old assistant reply and streams a fresh one.

    After the full regenerate + stream cycle the chat must contain exactly one
    user message (unchanged) and one assistant message (the new reply).  No
    duplicate user row is ever written.
    """
    user_id, chat_id = await _seed_chat(engine, make_user, "regen_user")
    maker = create_sessionmaker(engine)

    async with maker() as setup:
        repo = MessageRepo(setup)
        await repo.create(chat_id=chat_id, role="user", content="Вопрос")
        await repo.create(
            chat_id=chat_id, role="assistant", content="Старый ответ", incomplete=False
        )
        await setup.commit()

    service = ChatService(maker, FakeAgent(settings, "Новый ответ"))

    model, content, history = await service.regenerate_turn(user_id, chat_id)  # type: ignore[arg-type]
    assert content == "Вопрос"

    events = [e async for e in service.stream_turn(chat_id, model, content, history)]

    deltas = [e for e in events if isinstance(e, Delta)]
    done = [e for e in events if isinstance(e, Done)]
    assert "".join(d.text for d in deltas) == "Новый ответ"
    assert len(done) == 1

    async with maker() as check:
        stored = await MessageRepo(check).list(FieldEquals(Message.chat_id, chat_id))

    user_msgs = [m for m in stored if m.role == "user"]
    assistant_msgs = [m for m in stored if m.role == "assistant"]
    assert len(user_msgs) == 1
    assert len(assistant_msgs) == 1
    assert user_msgs[0].content == "Вопрос"
    assert assistant_msgs[0].content == "Новый ответ"


async def test_regenerate_turn_no_trailing_assistant_still_streams(
    engine: AsyncEngine,
    settings: Settings,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """regenerate_turn works even when the last user message has no assistant after it.

    Nothing is deleted; stream_turn simply produces a new assistant message.
    """
    user_id, chat_id = await _seed_chat(engine, make_user, "regen_noasst")
    maker = create_sessionmaker(engine)

    async with maker() as setup:
        repo = MessageRepo(setup)
        await repo.create(chat_id=chat_id, role="user", content="Привет")
        await setup.commit()

    service = ChatService(maker, FakeAgent(settings, "Ответ"))

    model, content, history = await service.regenerate_turn(user_id, chat_id)  # type: ignore[arg-type]
    assert content == "Привет"

    events = [e async for e in service.stream_turn(chat_id, model, content, history)]

    done = [e for e in events if isinstance(e, Done)]
    assert len(done) == 1

    async with maker() as check:
        stored = await MessageRepo(check).list(FieldEquals(Message.chat_id, chat_id))

    assert [m.role for m in stored] == ["user", "assistant"]
    assert len([m for m in stored if m.role == "user"]) == 1


async def test_regenerate_turn_raises_when_no_user_message(
    engine: AsyncEngine,
    settings: Settings,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """regenerate_turn raises NoUserMessageError when the chat has no user messages."""
    user_id, chat_id = await _seed_chat(engine, make_user, "regen_empty")
    maker = create_sessionmaker(engine)

    service = ChatService(maker, FakeAgent(settings, "x"))

    with pytest.raises(NoUserMessageError):
        await service.regenerate_turn(user_id, chat_id)  # type: ignore[arg-type]


async def test_regenerate_turn_rejects_missing_chat(
    engine: AsyncEngine,
    settings: Settings,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """regenerate_turn raises ChatNotFoundError for a non-existent chat."""
    user_id, _ = await _seed_chat(engine, make_user, "regen_ghost")
    maker = create_sessionmaker(engine)

    service = ChatService(maker, FakeAgent(settings, "x"))

    with pytest.raises(ChatNotFoundError):
        await service.regenerate_turn(user_id, uuid4())  # type: ignore[arg-type]


async def test_regenerate_turn_rejects_foreign_chat(
    engine: AsyncEngine,
    settings: Settings,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """regenerate_turn raises ChatNotFoundError when the chat belongs to another user."""
    _, chat_id = await _seed_chat(engine, make_user, "regen_owner")
    other_id, _ = await _seed_chat(engine, make_user, "regen_intruder")
    maker = create_sessionmaker(engine)

    service = ChatService(maker, FakeAgent(settings, "x"))

    with pytest.raises(ChatNotFoundError):
        await service.regenerate_turn(other_id, chat_id)  # type: ignore[arg-type]


async def test_regenerate_turn_rejects_unavailable_model(
    engine: AsyncEngine,
    settings: Settings,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """regenerate_turn raises ModelUnavailableError when the chat's model is not installed."""
    from capybara.agent import ModelUnavailableError

    maker = create_sessionmaker(engine)
    async with maker() as setup:
        user = await make_user(setup, username="regen_badmodel", display_name="B")
        chat = Chat(user_id=user.id, title="c", model="ghost:1b")
        setup.add(chat)
        await setup.commit()
        user_id, chat_id = user.id, chat.id

    service = ChatService(maker, FakeAgent(settings, "x"))

    with pytest.raises(ModelUnavailableError):
        await service.regenerate_turn(user_id, chat_id)  # type: ignore[arg-type]
