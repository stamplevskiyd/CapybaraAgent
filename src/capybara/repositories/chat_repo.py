from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from capybara.db.models import Chat


class ChatRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, user_id: UUID, title: str | None) -> Chat:
        chat = Chat(user_id=user_id)
        if title is not None:
            chat.title = title
        self._session.add(chat)
        await self._session.flush()
        return chat

    async def get(self, chat_id: UUID) -> Chat | None:
        return await self._session.get(Chat, chat_id)

    async def list_for_user(self, user_id: UUID) -> list[Chat]:
        stmt = select(Chat).where(Chat.user_id == user_id).order_by(Chat.updated_at.desc())
        return list((await self._session.execute(stmt)).scalars().all())

    async def touch(self, chat: Chat) -> None:
        from datetime import UTC, datetime

        chat.updated_at = datetime.now(UTC)
        await self._session.flush()
