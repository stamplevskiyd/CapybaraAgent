"""Shared helpers for MCP commands."""

import re
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from capybara.db.models import McpServer
from capybara.repositories.mcp_repo import McpServerRepo


def slugify(name: str) -> str:
    """Derive a tool-name prefix from a server name (lowercase alnum, ``_``-joined)."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or "mcp"


async def owned_server(session: AsyncSession, user_id: UUID, server_id: UUID) -> McpServer | None:
    """Return the server if it exists and belongs to *user_id*, else None."""
    server = await McpServerRepo(session).get(server_id)
    if server is None or server.user_id != user_id:
        return None
    return server
