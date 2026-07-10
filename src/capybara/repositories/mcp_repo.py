"""Repositories for MCP servers and their discovered tools."""

from uuid import UUID

from capybara.db.models import McpServer, McpTool
from capybara.repositories.base import BaseRepository


class McpServerRepo(BaseRepository[McpServer]):
    """Repository for MCP server rows (inherited CRUD only)."""

    model = McpServer


class McpToolRepo(BaseRepository[McpTool]):
    """Repository for MCP tool rows, with a per-server listing helper."""

    model = McpTool

    async def list_for_server(self, server_id: UUID) -> list[McpTool]:
        """Return all tools for *server_id*, in creation order."""
        return await self.list(McpTool.server_id == server_id)
