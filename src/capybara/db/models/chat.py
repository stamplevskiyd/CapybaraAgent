"""SQLAlchemy ORM model for the chats table."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from capybara.db.base import Base
from capybara.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from capybara.db.models.message import Message

#: Default title for a freshly created chat (before auto-title or manual rename).
DEFAULT_CHAT_TITLE = "Новый чат"


class Chat(Base, TimestampMixin):
    """ORM model representing a chat conversation owned by a user."""

    __tablename__ = "chats"
    __table_args__ = (Index("ix_chats_user_id_updated_at", "user_id", "updated_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default=DEFAULT_CHAT_TITLE)
    #: Selected LLM model for this chat, e.g. ``llama3.1:8b``. ``NULL`` = not yet chosen;
    #: there is no server-side fallback — an unset model blocks sending.
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: Whether the user has starred this chat; starred chats group at the top of the sidebar.
    is_favorite: Mapped[bool] = mapped_column(default=False, nullable=False)
    messages: Mapped[list[Message]] = relationship(
        back_populates="chat", cascade="all, delete-orphan"
    )
