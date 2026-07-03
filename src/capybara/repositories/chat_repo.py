"""Repository for Chat model access."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement

from capybara.db.models import Chat
from capybara.repositories.base import BaseRepository


class ChatRepo(BaseRepository[Chat]):
    """Repository for Chat CRUD and user-scoped queries."""

    model = Chat

    def _default_order_by(self) -> Sequence[ColumnElement[Any]]:
        """Order chats by most recently updated first."""
        return (Chat.updated_at.desc(),)

    async def create(self, user_id: UUID, title: str | None = None) -> Chat:  # type: ignore[override]
        """Create a chat for user_id, optionally setting a custom title."""
        fields: dict[str, Any] = {"user_id": user_id}
        if title is not None:
            fields["title"] = title
        return await super().create(**fields)

    async def touch(self, chat: Chat) -> None:
        """Update updated_at to now to mark a chat as recently active."""
        chat.updated_at = datetime.now(UTC)
        await self._session.flush()
