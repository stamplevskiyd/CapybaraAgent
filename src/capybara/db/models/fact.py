"""SQLAlchemy ORM model for the facts table (long-term memory)."""

from __future__ import annotations

from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from capybara.db.base import Base
from capybara.db.mixins import TimestampMixin

#: Fixed category set for a fact, coloured per the design handoff.
FACT_CATEGORIES: tuple[str, ...] = ("personal", "project", "preference")
#: How a fact was created: user-entered vs auto-captured from a conversation.
FACT_SOURCES: tuple[str, ...] = ("manual", "auto")
#: Embedding dimensionality — matches Ollama ``nomic-embed-text``.
EMBEDDING_DIM = 768

_CATEGORY_CHECK = ", ".join(f"'{c}'" for c in FACT_CATEGORIES)
_SOURCE_CHECK = ", ".join(f"'{s}'" for s in FACT_SOURCES)


class Fact(Base, TimestampMixin):
    """A single long-term memory fact owned by a user, with a vector embedding."""

    __tablename__ = "facts"
    # Short constraint labels only — the naming convention prefixes them
    # (``ck_facts_category`` / ``ix_facts_...``).
    __table_args__ = (
        CheckConstraint(f"category IN ({_CATEGORY_CHECK})", name="category"),
        CheckConstraint(f"source IN ({_SOURCE_CHECK})", name="source"),
        Index("ix_facts_user_id_created_at", "user_id", "created_at"),
        Index(
            "ix_facts_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    source: Mapped[str] = mapped_column(String(16))
