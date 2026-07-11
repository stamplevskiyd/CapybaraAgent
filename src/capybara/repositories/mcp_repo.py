"""Repositories for MCP servers and their discovered tools."""

from capybara.db.models import McpServer, McpTool
from capybara.repositories.base import BaseRepository


class McpServerRepo(BaseRepository[McpServer]):
    """Repository for MCP server rows (inherited CRUD; tools ride the relationship)."""

    model = McpServer


class McpToolRepo(BaseRepository[McpTool]):
    """Repository for MCP tool rows (inherited CRUD only)."""

    model = McpTool
