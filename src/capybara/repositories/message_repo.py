"""Repository for Message model access."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement

from capybara.db.models import Message
from capybara.repositories.base import BaseRepository


class MessageRepo(BaseRepository[Message]):
    """Repository for Message CRUD and chat-scoped queries."""

    model = Message

    def _default_order_by(self) -> Sequence[ColumnElement[Any]]:
        """Order messages by insertion sequence (monotonically increasing)."""
        return (Message.seq.asc(),)

    async def create(  # type: ignore[override]
        self,
        *,
        chat_id: UUID,
        role: str,
        content: str,
        model: str | None = None,
        usage_json: dict[str, Any] | None = None,
        incomplete: bool = False,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> Message:
        """Create and persist a new message row in the given chat."""
        return await super().create(
            chat_id=chat_id,
            role=role,
            content=content,
            model=model,
            usage_json=usage_json,
            incomplete=incomplete,
            tool_calls=tool_calls,
        )
