"""SQLAlchemy ORM model for the chats table."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from capybara.db.base import Base
from capybara.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from capybara.db.models.message import Message


class Chat(Base, TimestampMixin):
    """ORM model representing a chat conversation owned by a user."""

    __tablename__ = "chats"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="Новый чат")
    #: Selected LLM model for this chat, e.g. ``llama3.1:8b``. ``NULL`` = not yet chosen;
    #: there is no server-side fallback — an unset model blocks sending.
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    messages: Mapped[list[Message]] = relationship(
        back_populates="chat", cascade="all, delete-orphan"
    )
