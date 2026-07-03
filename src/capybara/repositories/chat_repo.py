"""Repository for Chat model access."""

from typing import Any
from uuid import UUID

from sqlalchemy import select

from capybara.db.models import Chat
from capybara.repositories.base import BaseRepository


class ChatRepo(BaseRepository[Chat]):
    """Repository for Chat CRUD and user-scoped queries."""

    model = Chat

    async def create(self, user_id: UUID, title: str | None = None) -> Chat:  # type: ignore[override]
        """Create a chat for user_id, optionally setting a custom title."""
        fields: dict[str, Any] = {"user_id": user_id}
        if title is not None:
            fields["title"] = title
        return await super().create(**fields)

    async def list_for_user(self, user_id: UUID) -> list[Chat]:
        """Return chats for a user ordered by most-recently updated first."""
        stmt = select(Chat).where(Chat.user_id == user_id).order_by(Chat.updated_at.desc())
        return list((await self._session.execute(stmt)).scalars().all())

    async def touch(self, chat: Chat) -> None:
        """Update updated_at to now to mark a chat as recently active."""
        from datetime import UTC, datetime

        chat.updated_at = datetime.now(UTC)
        await self._session.flush()
