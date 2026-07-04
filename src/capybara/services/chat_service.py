"""Chat service orchestrating message persistence and LLM streaming."""

from collections.abc import AsyncIterator
from uuid import UUID

from pydantic_ai.messages import ModelMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.agent.base import BaseAgent, ReplyAccumulator
from capybara.filters import FieldEquals
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.services.events import Delta, Done, StreamEvent


class ChatService:
    """Orchestrate a conversation turn: persist user/assistant messages and stream LLM reply."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], agent: BaseAgent) -> None:
        self._sessionmaker = sessionmaker
        self._agent = agent

    async def stream_turn(self, chat_id: UUID, user_content: str) -> AsyncIterator[StreamEvent]:
        """Stream a conversation turn, yielding Delta/Done events and persisting both messages.

        DB writes run on short-lived sessions rather than the request session so no
        connection is held for the duration of the LLM stream.  The user message is
        committed *before* streaming starts, so it survives even if the turn fails.

        If the stream fails mid-reply — an LLM or transport error — the partial text is
        persisted with ``incomplete=True`` before the exception propagates.  (On an
        abrupt task cancellation from a client disconnect the final write is
        best-effort: cancellation may abort it, but the user message is already saved.)
        """
        history = await self._load_history_and_save_user(chat_id, user_content)

        acc = ReplyAccumulator()
        completed = False
        assistant_id = ""
        try:
            async for delta in self._agent.stream_reply(user_content, history, acc):
                yield Delta(text=delta)
            completed = True
        finally:
            assistant_id = await self._persist_assistant(chat_id, acc, completed=completed)
        yield Done(message_id=assistant_id, usage=acc.usage)

    async def _load_history_and_save_user(
        self, chat_id: UUID, user_content: str
    ) -> list[ModelMessage]:
        """Load prior messages as model history and persist the incoming user message."""
        async with self._sessionmaker() as session:
            messages = MessageRepo(session)
            history_rows = await messages.list(FieldEquals("chat_id", chat_id))
            await messages.create(chat_id=chat_id, role="user", content=user_content)
            await session.commit()
        return self._agent.to_model_messages(history_rows)

    async def _persist_assistant(
        self, chat_id: UUID, acc: ReplyAccumulator, *, completed: bool
    ) -> str:
        """Persist the assistant message (partial if not completed) and touch the chat."""
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
            )
            chat = await chats.get(chat_id)
            if chat is not None:
                await chats.touch(chat)
            await session.commit()
            return str(assistant.id)
