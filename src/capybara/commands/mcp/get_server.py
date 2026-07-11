"""Fetch one user-owned MCP server."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.commands.base import BaseCommand
from capybara.commands.mcp.utils import owned_server
from capybara.db.models import McpServer


class GetMcpServer(BaseCommand[McpServer | None]):
    """Return a user-owned server (with tools), or None."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        user_id: UUID,
        server_id: UUID,
    ) -> None:
        """Store the sessionmaker and the (user, server) key."""
        self._sessionmaker = sessionmaker
        self._user_id = user_id
        self._server_id = server_id

    async def run(self) -> McpServer | None:
        """Fetch the server if owned."""
        async with self._sessionmaker() as session:
            return await owned_server(session, self._user_id, self._server_id)
