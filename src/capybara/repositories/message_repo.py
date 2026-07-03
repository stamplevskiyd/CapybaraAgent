"""Repository for Message model access."""

from uuid import UUID

from sqlalchemy import select

from capybara.db.models import Message
from capybara.repositories.base import BaseRepository


class MessageRepo(BaseRepository[Message]):
    """Repository for Message CRUD and chat-scoped queries."""

    model = Message

    async def list_for_chat(self, chat_id: UUID) -> list[Message]:
        """Return messages for a chat ordered by insertion sequence."""
        stmt = (
            select(Message).where(Message.chat_id == chat_id).order_by(Message.seq)
        )
        return list((await self._session.execute(stmt)).scalars().all())
