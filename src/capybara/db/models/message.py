"""SQLAlchemy ORM model for the messages table."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Identity, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from capybara.db.base import Base
from capybara.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from capybara.db.models.chat import Chat

#: Roles a stored message may carry. Slice 1 only produces ``user`` and ``assistant``;
#: ``system`` and others are out of scope until a later slice relaxes this constraint.
MESSAGE_ROLES: tuple[str, ...] = ("user", "assistant")

_ROLE_CHECK = ", ".join(f"'{role}'" for role in MESSAGE_ROLES)


class Message(Base, TimestampMixin):
    """ORM model representing a single message within a chat."""

    __tablename__ = "messages"
    # Short label only — the naming convention prefixes it to ``ck_messages_role``.
    __table_args__ = (CheckConstraint(f"role IN ({_ROLE_CHECK})", name="role"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    chat_id: Mapped[UUID] = mapped_column(ForeignKey("chats.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    usage_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    incomplete: Mapped[bool] = mapped_column(default=False)
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    chat: Mapped[Chat] = relationship(back_populates="messages")
