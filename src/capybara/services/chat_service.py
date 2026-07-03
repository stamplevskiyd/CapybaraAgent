from collections.abc import AsyncIterator
from uuid import UUID

from capybara.agent.base import BaseAgent, ReplyAccumulator
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.services.events import Delta, Done, StreamEvent


class ChatService:
    def __init__(
        self, chats: ChatRepo, messages: MessageRepo, agent: BaseAgent
    ) -> None:
        self._chats = chats
        self._messages = messages
        self._agent = agent

    async def stream_turn(
        self, chat_id: UUID, user_content: str
    ) -> AsyncIterator[StreamEvent]:
        history_rows = await self._messages.list_for_chat(chat_id)
        await self._messages.create(chat_id=chat_id, role="user", content=user_content)
        history = self._agent.to_model_messages(history_rows)

        acc = ReplyAccumulator()
        completed = False
        done_event: Done | None = None
        try:
            async for delta in self._agent.stream_reply(user_content, history, acc):
                yield Delta(text=delta)
            completed = True
        finally:
            assistant = await self._messages.create(
                chat_id=chat_id,
                role="assistant",
                content=acc.text,
                model=acc.model,
                usage_json=acc.usage,
                incomplete=not completed,
            )
            chat = await self._chats.get(chat_id)
            if chat is not None:
                await self._chats.touch(chat)
            if completed:
                done_event = Done(message_id=str(assistant.id), usage=acc.usage)
        if done_event is not None:
            yield done_event
