from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from capybara.db.models import Message


class MessageRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        chat_id: UUID,
        role: str,
        content: str,
        *,
        model: str | None = None,
        usage: dict[str, Any] | None = None,
        incomplete: bool = False,
    ) -> Message:
        message = Message(
            chat_id=chat_id,
            role=role,
            content=content,
            model=model,
            usage_json=usage,
            incomplete=incomplete,
        )
        self._session.add(message)
        await self._session.flush()
        return message

    async def list_for_chat(self, chat_id: UUID) -> list[Message]:
        stmt = (
            select(Message).where(Message.chat_id == chat_id).order_by(Message.seq)
        )
        return list((await self._session.execute(stmt)).scalars().all())
