"""Repository for Message model access."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement

from capybara.db.models import Message
from capybara.repositories.base import BaseRepository


class MessageRepo(BaseRepository[Message]):
    """Repository for Message CRUD and chat-scoped queries."""

    model = Message

    def _default_order_by(self) -> Sequence[ColumnElement[Any]]:
        """Order messages by insertion sequence (monotonically increasing)."""
        return (Message.seq.asc(),)
