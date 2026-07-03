"""SQLAlchemy ORM model for the messages table."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, ForeignKey, Identity, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from capybara.db.base import Base
from capybara.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from capybara.db.models.chat import Chat


class Message(Base, TimestampMixin):
    """ORM model representing a single message within a chat."""

    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    chat_id: Mapped[UUID] = mapped_column(ForeignKey("chats.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    usage_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    incomplete: Mapped[bool] = mapped_column(default=False)
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    chat: Mapped[Chat] = relationship(back_populates="messages")
