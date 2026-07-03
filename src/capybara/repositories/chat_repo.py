from typing import Any
from uuid import UUID

from sqlalchemy import select

from capybara.db.models import Chat
from capybara.repositories.base import BaseRepository


class ChatRepo(BaseRepository[Chat]):
    model = Chat

    async def create(self, user_id: UUID, title: str | None = None) -> Chat:  # type: ignore[override]
        fields: dict[str, Any] = {"user_id": user_id}
        if title is not None:
            fields["title"] = title
        return await super().create(**fields)

    async def list_for_user(self, user_id: UUID) -> list[Chat]:
        stmt = select(Chat).where(Chat.user_id == user_id).order_by(Chat.updated_at.desc())
        return list((await self._session.execute(stmt)).scalars().all())

    async def touch(self, chat: Chat) -> None:
        from datetime import UTC, datetime

        chat.updated_at = datetime.now(UTC)
        await self._session.flush()
