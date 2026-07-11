"""SQLAlchemy ORM model for chat_prefs: per-user metadata for Chainlit threads."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from capybara.db.base import Base
from capybara.db.mixins import TimestampMixin


class ChatPref(Base, TimestampMixin):
    """Per-user preferences for a Chainlit chat thread (favorite, selected model).

    Chainlit owns the thread and its title (``thread.name``); this table only holds the
    extras Chainlit has no concept of. ``thread_id`` is a soft reference to
    ``chainlit.threads.id`` — no cross-schema FK — so the two schemas stay decoupled.
    """

    __tablename__ = "chat_prefs"
    __table_args__ = (
        UniqueConstraint("user_id", "thread_id", name="user_id_thread_id"),
        CheckConstraint("mode IN ('fast', 'smart')", name="mode"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    thread_id: Mapped[UUID] = mapped_column(Uuid)
    is_favorite: Mapped[bool] = mapped_column(default=False)
    model: Mapped[str | None] = mapped_column(String(200), default=None)
    #: Agent runtime for this thread: 'fast' (simple react loop) or 'smart' (DeepAgents).
    mode: Mapped[str] = mapped_column(String(8), default="fast", nullable=False)
