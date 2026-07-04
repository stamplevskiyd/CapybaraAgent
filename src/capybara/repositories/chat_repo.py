"""Repository for Chat model access."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, func

from capybara.db.models import Chat
from capybara.repositories.base import BaseRepository


class ChatRepo(BaseRepository[Chat]):
    """Repository for Chat CRUD and user-scoped queries."""

    model = Chat

    def _default_order_by(self) -> Sequence[ColumnElement[Any]]:
        """Order chats by most recently updated first."""
        return (Chat.updated_at.desc(),)

    async def create(  # type: ignore[override]
        self, user_id: UUID, title: str | None = None, model: str | None = None
    ) -> Chat:
        """Create a chat for user_id, optionally setting a custom title and model."""
        fields: dict[str, Any] = {"user_id": user_id}
        if title is not None:
            fields["title"] = title
        if model is not None:
            fields["model"] = model
        return await super().create(**fields)

    async def touch(self, chat: Chat) -> None:
        """Mark a chat as recently active by bumping updated_at to the DB clock.

        Uses ``func.now()`` (server-side) rather than the app clock so ordering by
        updated_at stays consistent with server_default/onupdate timestamps and is
        immune to app/DB clock skew.
        """
        chat.updated_at = func.now()
        await self._session.flush()
