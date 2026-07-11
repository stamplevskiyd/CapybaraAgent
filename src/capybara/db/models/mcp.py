"""SQLAlchemy ORM models for MCP servers and their discovered tools."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from capybara.db.base import Base
from capybara.db.mixins import TimestampMixin


class McpServer(Base, TimestampMixin):
    """A remote (HTTP/SSE) MCP server config owned by a user.

    ``headers`` holds arbitrary HTTP headers (auth lives here, e.g. ``Authorization``).
    NOTE: headers are stored as plain JSON and are NOT encrypted at rest — a known
    limitation tracked for a dedicated follow-up slice.
    """

    __tablename__ = "mcp_servers"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(Text)
    headers: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_connected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Discovered tools; ``selectin`` keeps them loaded on every server read (they are
    #: needed by the API and per-turn tool assembly alike), which async requires anyway.
    tools: Mapped[list[McpTool]] = relationship(
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="McpTool.created_at",
    )


class McpTool(Base, TimestampMixin):
    """A single tool discovered from an MCP server, with a per-tool ``enabled`` flag.

    ``enabled`` is the curation control: only enabled tools of enabled servers are ever
    offered to the chat agent, so a large server (e.g. Home Assistant) can be trimmed to
    the tools a local model handles well.
    """

    __tablename__ = "mcp_tools"
    __table_args__ = (
        UniqueConstraint("server_id", "name"),
        Index("ix_mcp_tools_server_id", "server_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    server_id: Mapped[UUID] = mapped_column(ForeignKey("mcp_servers.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
