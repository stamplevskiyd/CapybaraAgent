"""Chat service orchestrating message persistence and LLM streaming."""

from collections.abc import AsyncIterator
from uuid import UUID

from pydantic_ai.messages import ModelMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.agent.base import BaseAgent, ReplyAccumulator
from capybara.db.models import Message
from capybara.filters import FieldEquals
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.services.events import Delta, Done, StreamEvent


class ChatNotFoundError(Exception):
    """Raised when a chat does not exist or is not owned by the requesting user."""

    def __init__(self, chat_id: UUID) -> None:
        super().__init__(f"Chat {chat_id} not found")
        self.chat_id = chat_id


class ChatService:
    """Orchestrate a conversation turn: persist user/assistant messages and stream LLM reply."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], agent: BaseAgent) -> None:
        self._sessionmaker = sessionmaker
        self._agent = agent

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
        async with self._sessionmaker() as session:
            chats = ChatRepo(session)
            chat = await chats.get(chat_id)
            if chat is None or chat.user_id != user_id:
                raise ChatNotFoundError(chat_id)
            await self._agent.ensure_available(chat.model)
            model = chat.model
            assert model is not None  # ensure_available rejects None
            messages = MessageRepo(session)
            history_rows = await messages.list(
                FieldEquals(Message.chat_id, chat_id),
                FieldEquals(Message.incomplete, False),
            )
            await messages.create(chat_id=chat_id, role="user", content=user_content)
            await session.commit()
        return model, self._agent.to_model_messages(history_rows)

    async def stream_turn(
        self, chat_id: UUID, model_name: str, user_content: str, history: list[ModelMessage]
    ) -> AsyncIterator[StreamEvent]:
        """Stream the LLM reply as Delta events and persist the assistant message.

        No DB connection is held while the model streams; the assistant message is
        written afterwards on its own short-lived session.

        If the stream fails after some tokens, the partial text is persisted with
        ``incomplete=True`` before the error propagates.  If it fails *before* the first
        token — e.g. the LLM erroring immediately — nothing is written, so a failed turn
        never pollutes chat history with a blank assistant message.
        """
        acc = ReplyAccumulator()
        completed = False
        try:
            async for delta in self._agent.stream_reply(model_name, user_content, history, acc):
                yield Delta(text=delta)
            completed = True
        finally:
            assistant_id = await self._persist_assistant(chat_id, acc, completed=completed)
        if assistant_id is not None:
            yield Done(message_id=assistant_id, usage=acc.usage)

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
            )
            chat = await chats.get(chat_id)
            if chat is not None:
                await chats.touch(chat)
            await session.commit()
            return str(assistant.id)
