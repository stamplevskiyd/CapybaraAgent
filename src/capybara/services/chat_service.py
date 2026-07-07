"""Chat service orchestrating message persistence and LLM streaming."""

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import UUID

import anyio
from pydantic_ai import Tool
from pydantic_ai.messages import ModelMessage
from pydantic_ai.toolsets import AbstractToolset
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.agent.base import (
    BaseAgent,
    ReplyAccumulator,
    StreamedText,
    StreamedToolCall,
    StreamedToolResult,
)
from capybara.db.models import Message
from capybara.db.models.chat import DEFAULT_CHAT_TITLE
from capybara.filters import FieldEquals
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.services.events import Delta, Done, StreamEvent, ToolCall, ToolResult
from capybara.services.mcp_service import McpService
from capybara.services.memory_service import MemoryService
from capybara.services.memory_tools import make_recall_tool

logger = logging.getLogger(__name__)


class ChatNotFoundError(Exception):
    """Raised when a chat does not exist or is not owned by the requesting user."""

    def __init__(self, chat_id: UUID) -> None:
        """Record the missing chat id."""
        super().__init__(f"Chat {chat_id} not found")
        self.chat_id = chat_id


class NoUserMessageError(Exception):
    """Raised when regenerate is requested on a chat that has no user messages."""

    def __init__(self, chat_id: UUID) -> None:
        """Record the chat id that contained no user message."""
        super().__init__(f"Chat {chat_id} has no user message to regenerate")
        self.chat_id = chat_id


class ChatTurnLocks:
    """Per-chat async locks that serialize concurrent turns and regenerations.

    A turn spans begin/regenerate → stream → persist across two request handlers, so
    without serialization two overlapping sends (or a send racing a regenerate) on the
    same chat interleave: both user messages land before either reply, or a regenerate
    deletes an in-flight reply. One registry is shared app-wide (a ChatService is built
    per request) so the lock for a given chat is the same object across requests.
    """

    def __init__(self) -> None:
        """Start with no locks; one is created lazily on first use per chat."""
        self._locks: dict[UUID, asyncio.Lock] = {}

    def lock_for(self, chat_id: UUID) -> asyncio.Lock:
        """Return the lock for *chat_id*, creating it on first request."""
        lock = self._locks.get(chat_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[chat_id] = lock
        return lock


class TurnLockLease:
    """A held per-chat turn lock with idempotent release.

    A turn's lock is acquired in the request handler but must be releasable from
    whichever cleanup path actually runs — the SSE generator's ``finally`` on streams
    that started, or the response object's ``finally`` when the client disconnected
    before the body was ever pulled — so ``release`` must tolerate repeated calls.
    """

    def __init__(self, lock: asyncio.Lock) -> None:
        """Wrap an already-acquired lock."""
        self._lock = lock
        self._released = False

    def release(self) -> None:
        """Release the underlying lock on first call; later calls are no-ops."""
        if not self._released:
            self._released = True
            self._lock.release()


class ChatService:
    """Orchestrate a conversation turn: persist user/assistant messages and stream LLM reply."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        agent: BaseAgent,
        memory_service: MemoryService | None = None,
        turn_locks: ChatTurnLocks | None = None,
        mcp_service: McpService | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._agent = agent
        self._memory_service = memory_service
        # A standalone registry by default keeps unit tests self-contained; the app wires
        # the shared registry so locks span concurrent requests.
        self._turn_locks = turn_locks or ChatTurnLocks()
        self._mcp_service = mcp_service

    async def acquire_turn_lock(self, chat_id: UUID) -> TurnLockLease:
        """Acquire this chat's turn lock and return an idempotently-releasable lease.

        The lock serializes the chat's turns and is held across a full turn
        (begin/regenerate → stream → persist).
        """
        lock = self._turn_locks.lock_for(chat_id)
        await lock.acquire()
        return TurnLockLease(lock)

    async def begin_turn(
        self, user_id: UUID, chat_id: UUID, user_content: str
    ) -> tuple[str, list[ModelMessage]]:
        """Verify ownership, validate the model, persist the user message, load history.

        The model on the chat is validated against the provider's live list *before* the
        user message is written, so an unusable model never leaves an orphaned message and
        the error surfaces before any SSE bytes are sent.

        Returns:
            The validated model name and the pydantic-ai history.

        Raises:
            ChatNotFoundError: If the chat does not exist or is not owned by *user_id*.
            ModelUnavailableError: If the chat's model is unset or not installed.
            ModelProviderError: If the model provider cannot be reached.
        """
        # Read ownership, model, and history on a short-lived session that is released
        # *before* the provider model-check, so a slow/hung Ollama never holds a Postgres
        # connection open and exhausts the pool.
        async with self._sessionmaker() as session:
            chats = ChatRepo(session)
            chat = await chats.get(chat_id)
            if chat is None or chat.user_id != user_id:
                raise ChatNotFoundError(chat_id)
            model = chat.model
            messages = MessageRepo(session)
            history_rows = await messages.list(
                FieldEquals(Message.chat_id, chat_id),
                FieldEquals(Message.incomplete, False),
            )
        # No DB connection is held here. Still validated before the user message is
        # written, so an unusable model never leaves an orphaned message.
        model = await self._agent.ensure_available(model)
        async with self._sessionmaker() as session:
            chats = ChatRepo(session)
            chat = await chats.get(chat_id)
            if chat is None or chat.user_id != user_id:
                raise ChatNotFoundError(chat_id)
            messages = MessageRepo(session)
            await messages.create(chat_id=chat_id, role="user", content=user_content)
            await chats.touch(chat)
            await session.commit()
        return model, self._agent.to_model_messages(history_rows)

    async def stream_turn(
        self,
        chat_id: UUID,
        model_name: str,
        user_content: str,
        history: list[ModelMessage],
        *,
        user_id: UUID | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream the LLM reply as Delta events and persist the assistant message.

        No DB connection is held while the model streams. When *user_id* is given and a
        memory service is wired, the recall tool is added to the run's tool list so the
        model can search long-term memory mid-turn.

        If the stream fails after some tokens — including cancellation when the client
        disconnects — the partial text is persisted with ``incomplete=True`` before the
        error propagates. If it fails before the first token, nothing is written, so a
        failed turn never leaves a blank assistant message.
        """
        tools: list[Tool[None]] = []
        if user_id is not None and self._memory_service is not None:
            tools.append(make_recall_tool(self._memory_service, user_id))
        toolsets: list[AbstractToolset[None]] = []
        if user_id is not None and self._mcp_service is not None:
            toolsets = await self._mcp_service.build_toolsets(user_id)
        acc = ReplyAccumulator()
        completed = False
        try:
            async for event in self._agent.stream_reply(
                model_name, user_content, history, acc, tools=tools, toolsets=toolsets
            ):
                if isinstance(event, StreamedText):
                    yield Delta(text=event.text)
                elif isinstance(event, StreamedToolCall):
                    yield ToolCall(id=event.id, name=event.name, args=event.args)
                elif isinstance(event, StreamedToolResult):
                    yield ToolResult(id=event.id, result=event.result)
            completed = True
        finally:
            # A client disconnect cancels this generator, and the cancellation is
            # re-delivered at every subsequent await — shield the persist or the
            # partial reply (and its incomplete marker) would be silently lost.
            with anyio.CancelScope(shield=True):
                assistant_id = await self._persist_assistant(chat_id, acc, completed=completed)
        if completed:
            yield Done(message_id=assistant_id, usage=acc.usage)

    async def regenerate_turn(
        self, user_id: UUID, chat_id: UUID
    ) -> tuple[str, str, list[ModelMessage]]:
        """Prepare a regeneration: delete trailing assistant messages, return stream params.

        Validates ownership and model availability before any mutation.  All
        messages with a sequence number higher than the last user message are
        removed so that ``stream_turn`` can write a fresh assistant reply
        without leaving duplicate rows.

        Returns:
            A 3-tuple of ``(model_name, last_user_content, history)`` suitable
            for passing directly to ``stream_turn``.

        Raises:
            ChatNotFoundError: If the chat does not exist or is not owned by *user_id*.
            NoUserMessageError: If the chat contains no user messages to regenerate from.
            ModelUnavailableError: If the chat's model is unset or not installed.
            ModelProviderError: If the model provider cannot be reached.
        """
        # Read ownership, model, and messages on a short-lived session that is released
        # *before* the provider model-check (same pattern as begin_turn), so a slow/hung
        # Ollama never holds a Postgres connection open and exhausts the pool.
        async with self._sessionmaker() as session:
            chats = ChatRepo(session)
            chat = await chats.get(chat_id)
            if chat is None or chat.user_id != user_id:
                raise ChatNotFoundError(chat_id)
            model = chat.model
            messages = MessageRepo(session)
            all_messages = await messages.list(FieldEquals(Message.chat_id, chat_id))

        # No DB connection is held here. Still validated before any mutation.
        model = await self._agent.ensure_available(model)

        # Find the last user message (highest seq among role=="user")
        last_user: Message | None = None
        for msg in reversed(all_messages):
            if msg.role == "user":
                last_user = msg
                break

        if last_user is None:
            raise NoUserMessageError(chat_id)

        # History is all complete messages strictly before the last user message
        history_rows = [m for m in all_messages if m.seq < last_user.seq and not m.incomplete]
        last_user_content = last_user.content

        # Delete every message that trails the last user message (complete or incomplete)
        # on a fresh session. The caller holds the per-chat turn lock across the whole
        # regenerate, so the message set cannot change between the read and this delete.
        async with self._sessionmaker() as session:
            chats = ChatRepo(session)
            chat = await chats.get(chat_id)
            if chat is None or chat.user_id != user_id:
                raise ChatNotFoundError(chat_id)
            messages = MessageRepo(session)
            trailing = await messages.list(FieldEquals(Message.chat_id, chat_id))
            for msg in trailing:
                if msg.seq > last_user.seq:
                    await messages.delete(msg)
            await session.commit()

        return model, last_user_content, self._agent.to_model_messages(history_rows)

    async def generate_title(self, chat_id: UUID, first_user_message: str) -> str | None:
        """Generate and persist a chat title from the first user message.

        Only acts on a chat that still has the default title and a selected model; returns
        the new title, or ``None`` when skipped or on failure. Never raises — a title is a
        nicety and must not affect the reply stream.
        """
        try:
            async with self._sessionmaker() as session:
                chat = await ChatRepo(session).get(chat_id)
                if chat is None or chat.title != DEFAULT_CHAT_TITLE or chat.model is None:
                    return None
                model = chat.model
            # Generate with no DB connection held; the provider call can be slow.
            title = await self._agent.generate_title(model, first_user_message)
            if not title.strip():
                return None
            async with self._sessionmaker() as session:
                chats = ChatRepo(session)
                chat = await chats.get(chat_id)
                if chat is None or chat.title != DEFAULT_CHAT_TITLE:
                    return None  # deleted or renamed while the title was generating
                await chats.update(chat, title=title)
                await session.commit()
                return title
        except Exception:
            logger.exception("title generation failed for chat %s", chat_id)
            return None

    async def _persist_assistant(
        self, chat_id: UUID, acc: ReplyAccumulator, *, completed: bool
    ) -> str | None:
        """Persist the assistant message (partial if not completed) and touch the chat.

        Returns the new message id, or ``None`` if no text was produced — an empty reply
        is not worth a row and must never re-enter the model context as history.
        """
        if not acc.text:
            return None
        async with self._sessionmaker() as session:
            messages = MessageRepo(session)
            chats = ChatRepo(session)
            assistant = await messages.create(
                chat_id=chat_id,
                role="assistant",
                content=acc.text,
                model=acc.model,
                usage_json=acc.usage,
                incomplete=not completed,
                tool_calls=acc.tool_calls or None,
            )
            chat = await chats.get(chat_id)
            if chat is not None:
                await chats.touch(chat)
            await session.commit()
            return str(assistant.id)
