from datetime import UTC, datetime
from uuid import uuid4

import anyio
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from capybara.config import Settings
from capybara.db.engine import create_sessionmaker
from capybara.db.models import Chat, Message
from capybara.filters import FieldEquals
from capybara.repositories.message_repo import MessageRepo
from capybara.services.chat_service import ChatNotFoundError, ChatService, NoUserMessageError
from capybara.services.events import Delta, Done, ToolCall, ToolResult
from support import (
    FakeAgent,
    PartialThenFailAgent,
    PartialThenHangAgent,
    RaisingAgent,
    ScriptedToolAgent,
)


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


async def test_stream_turn_persists_partial_when_cancelled_mid_stream(
    engine: AsyncEngine,
    settings: Settings,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """A client disconnect mid-stream must still persist the partial reply.

    Starlette delivers a disconnect as anyio cancellation, which keeps re-raising
    CancelledError at every unshielded await until the task exits — including the
    persistence awaits in stream_turn's cleanup. The persist must be shielded, or
    the partial text (and its incomplete marker) is silently lost.
    """
    user_id, chat_id = await _seed_chat(engine, make_user, "disconnect_user")
    maker = create_sessionmaker(engine)

    service = ChatService(maker, PartialThenHangAgent(settings, "Частич"))

    model, history = await service.begin_turn(user_id, chat_id, "Вопрос")  # type: ignore[arg-type]
    with anyio.CancelScope() as scope:
        async for event in service.stream_turn(chat_id, model, "Вопрос", history):  # type: ignore[arg-type]
            if isinstance(event, Delta):
                scope.cancel()
    assert scope.cancelled_caught

    async with maker() as check:
        stored = await MessageRepo(check).list(FieldEquals(Message.chat_id, chat_id))
    assert [m.role for m in stored] == ["user", "assistant"]
    assert stored[-1].content == "Частич"
    assert stored[-1].incomplete is True


async def test_begin_turn_touches_chat_when_user_message_is_saved(
    engine: AsyncEngine,
    settings: Settings,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """A saved user turn bumps chat recency even if the assistant later fails."""
    maker = create_sessionmaker(engine)
    old_time = datetime(2020, 1, 1, tzinfo=UTC)
    async with maker() as setup:
        user = await make_user(setup, username="touch_user", display_name="Touch")
        chat = Chat(user_id=user.id, title="c", model="test-model", updated_at=old_time)
        setup.add(chat)
        await setup.commit()
        user_id, chat_id = user.id, chat.id

    service = ChatService(maker, RaisingAgent(settings, "boom"))
    model, history = await service.begin_turn(user_id, chat_id, "Вопрос")  # type: ignore[arg-type]
    with pytest.raises(RuntimeError):
        async for _ in service.stream_turn(chat_id, model, "Вопрос", history):  # type: ignore[arg-type]
            pass

    async with maker() as check:
        reloaded = await check.get(Chat, chat_id)
        assert reloaded is not None
        assert reloaded.updated_at > old_time


async def test_begin_turn_holds_no_session_during_model_check(
    engine: AsyncEngine,
    settings: Settings,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """The provider model-check must not run while a DB connection is held.

    A slow/hung Ollama holding a Postgres connection open would exhaust the pool. This
    pins the fix: with a size-1 pool, an agent that itself touches the DB during the
    model check would deadlock if begin_turn still held its session across the call.
    """
    user_id, chat_id = await _seed_chat(engine, make_user, "poolguard")
    # Single connection, no overflow, fail fast instead of hanging if exhausted.
    limited = create_async_engine(
        settings.database_url, pool_size=1, max_overflow=0, pool_timeout=1
    )
    maker = create_sessionmaker(limited)

    class SessionProbingAgent(FakeAgent):
        async def list_models(self) -> list[str]:
            # Acquire a second connection while the caller checks the model; this
            # exhausts the size-1 pool iff begin_turn is still holding its session.
            async with maker() as probe:
                await probe.execute(sa.text("SELECT 1"))
            return list(self._models)

    service = ChatService(maker, SessionProbingAgent(settings, "x"))
    try:
        model, _history = await service.begin_turn(user_id, chat_id, "Вопрос")  # type: ignore[arg-type]
        assert model == "test-model"
    finally:
        await limited.dispose()


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


async def test_regenerate_turn_holds_no_session_during_model_check(
    engine: AsyncEngine,
    settings: Settings,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """The regenerate model-check must not run while a DB connection is held.

    Mirrors test_begin_turn_holds_no_session_during_model_check: with a size-1 pool,
    an agent that itself touches the DB during the model check deadlocks iff
    regenerate_turn still holds its read session across the provider call.
    """
    user_id, chat_id = await _seed_chat(engine, make_user, "regen_poolguard")
    seed_maker = create_sessionmaker(engine)
    async with seed_maker() as setup:
        repo = MessageRepo(setup)
        await repo.create(chat_id=chat_id, role="user", content="Вопрос")
        await repo.create(chat_id=chat_id, role="assistant", content="Старый", incomplete=False)
        await setup.commit()

    # Single connection, no overflow, fail fast instead of hanging if exhausted.
    limited = create_async_engine(
        settings.database_url, pool_size=1, max_overflow=0, pool_timeout=1
    )
    maker = create_sessionmaker(limited)

    class SessionProbingAgent(FakeAgent):
        async def list_models(self) -> list[str]:
            # Acquire a second connection while the caller checks the model; this
            # exhausts the size-1 pool iff regenerate_turn is still holding its session.
            async with maker() as probe:
                await probe.execute(sa.text("SELECT 1"))
            return list(self._models)

    service = ChatService(maker, SessionProbingAgent(settings, "x"))
    try:
        model, content, _history = await service.regenerate_turn(user_id, chat_id)  # type: ignore[arg-type]
        assert model == "test-model"
        assert content == "Вопрос"
    finally:
        await limited.dispose()


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


async def test_generate_title_sets_title_only_when_default(
    engine: AsyncEngine,
    settings: Settings,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """Title is generated for a default-titled chat, and skipped for a renamed one."""
    maker = create_sessionmaker(engine)
    async with maker() as setup:
        user = await make_user(setup, username="titler", display_name="T")
        default_chat = Chat(user_id=user.id, model="test-model")  # title defaults
        named_chat = Chat(user_id=user.id, title="Моё имя", model="test-model")
        setup.add_all([default_chat, named_chat])
        await setup.commit()
        default_id, named_id = default_chat.id, named_chat.id

    service = ChatService(maker, FakeAgent(settings, "Сгенерённый заголовок"))

    t1 = await service.generate_title(default_id, "О чём поговорим?")
    assert t1 == "Сгенерённый заголовок"
    t2 = await service.generate_title(named_id, "О чём поговорим?")
    assert t2 is None  # already has a custom title → skipped

    async with maker() as check:
        from capybara.repositories.chat_repo import ChatRepo

        assert (await ChatRepo(check).get(default_id)).title == "Сгенерённый заголовок"  # type: ignore[union-attr]
        assert (await ChatRepo(check).get(named_id)).title == "Моё имя"  # type: ignore[union-attr]


async def test_generate_title_keeps_default_when_output_blank(
    engine: AsyncEngine,
    settings: Settings,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """A blank generated title never overwrites the default title."""
    from capybara.db.models.chat import DEFAULT_CHAT_TITLE
    from capybara.repositories.chat_repo import ChatRepo

    maker = create_sessionmaker(engine)
    async with maker() as setup:
        user = await make_user(setup, username="blanktitle", display_name="B")
        chat = Chat(user_id=user.id, model="test-model")  # default title
        setup.add(chat)
        await setup.commit()
        chat_id = chat.id

    # FakeAgent with empty output → _clean_title falls back to the (whitespace) message → "".
    service = ChatService(maker, FakeAgent(settings, ""))
    result = await service.generate_title(chat_id, "   ")
    assert result is None

    async with maker() as check:
        reloaded = await ChatRepo(check).get(chat_id)
        assert reloaded is not None
        assert reloaded.title == DEFAULT_CHAT_TITLE


async def test_stream_turn_emits_and_persists_tool_calls(
    engine: AsyncEngine,
    settings: Settings,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """Tool call/result events are streamed in order and stored on the assistant row."""
    user_id, chat_id = await _seed_chat(engine, make_user, "tool_user")
    maker = create_sessionmaker(engine)

    service = ChatService(maker, ScriptedToolAgent(settings, "Ответ"))

    model, history = await service.begin_turn(user_id, chat_id, "Что я люблю?")  # type: ignore[arg-type]
    events = [
        e
        async for e in service.stream_turn(chat_id, model, "Что я люблю?", history, user_id=user_id)
    ]

    kinds = [type(e).__name__ for e in events]
    assert kinds.index("ToolCall") < kinds.index("ToolResult") < kinds.index("Delta")
    call = next(e for e in events if isinstance(e, ToolCall))
    res = next(e for e in events if isinstance(e, ToolResult))
    assert call.name == "recall" and call.args == {"query": "любимое"}
    assert res.id == call.id and "походы" in res.result
    assert any(isinstance(e, Done) for e in events)

    async with maker() as check:
        stored = await MessageRepo(check).list(FieldEquals(Message.chat_id, chat_id))
    assistant = stored[-1]
    assert assistant.role == "assistant"
    assert assistant.tool_calls == [
        {
            "id": "call-1",
            "name": "recall",
            "args": {"query": "любимое"},
            "result": "- [personal] походы",
        }
    ]


async def test_stream_turn_completes_when_mcp_build_returns_empty(
    engine: AsyncEngine,
    settings: Settings,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """stream_turn completes normally when build_toolsets returns [] (fail-open, skip path).

    Proves that a dead/skipped MCP server (build_toolsets → []) never prevents the plain
    assistant reply from completing: the turn must yield a Done event without raising.
    """
    maker = create_sessionmaker(engine)
    async with maker() as setup:
        user = await make_user(setup, username="mcp_empty_user", display_name="M")
        chat = Chat(user_id=user.id, title="t", model="test-model")
        setup.add(chat)
        await setup.flush()
        setup.add(Message(chat_id=chat.id, role="user", content="привет?"))
        await setup.commit()

    class _EmptyMcp:
        async def build_toolsets(self, user_id):  # type: ignore[no-untyped-def]
            return []

    service = ChatService(maker, FakeAgent(settings, "Ответ"), mcp_service=_EmptyMcp())

    events = [
        e async for e in service.stream_turn(chat.id, "test-model", "привет?", [], user_id=user.id)
    ]

    assert any(isinstance(e, Done) for e in events)


async def test_stream_turn_surfaces_mcp_toolset_tool(
    engine: AsyncEngine,
    settings: Settings,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """An MCP toolset from McpService.build_toolsets surfaces as ToolCall/ToolResult events."""
    from pydantic_ai.toolsets import FunctionToolset

    from support import ToolCallingFakeAgent

    maker = create_sessionmaker(engine)
    async with maker() as setup:
        user = await make_user(setup)
        chat = Chat(user_id=user.id, title="t", model="test-model")
        setup.add(chat)
        await setup.flush()
        setup.add(Message(chat_id=chat.id, role="user", content="погода?"))
        await setup.commit()

    def weather(city: str) -> str:
        """Return the weather for a city."""
        return "sunny in " + city

    class _FakeMcp:
        async def build_toolsets(self, user_id):  # type: ignore[no-untyped-def]
            return [FunctionToolset([weather]).prefixed("home")]

    service = ChatService(maker, ToolCallingFakeAgent(settings, "Готово"), mcp_service=_FakeMcp())

    events = [
        e async for e in service.stream_turn(chat.id, "test-model", "погода?", [], user_id=user.id)
    ]

    assert any(isinstance(e, ToolCall) and e.name == "home_weather" for e in events)
    assert any(isinstance(e, ToolResult) and "sunny" in e.result for e in events)
