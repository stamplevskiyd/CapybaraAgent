from uuid import UUID

from sqlalchemy import select

from capybara.db.models import Message
from capybara.repositories.base import BaseRepository


class MessageRepo(BaseRepository[Message]):
    model = Message

    async def list_for_chat(self, chat_id: UUID) -> list[Message]:
        stmt = (
            select(Message).where(Message.chat_id == chat_id).order_by(Message.seq)
        )
        return list((await self._session.execute(stmt)).scalars().all())
