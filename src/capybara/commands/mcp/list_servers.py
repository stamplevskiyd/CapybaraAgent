"""List a user's MCP servers."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.commands.base import BaseCommand
from capybara.db.models import McpServer
from capybara.filters import FieldEquals
from capybara.repositories.mcp_repo import McpServerRepo


class ListMcpServers(BaseCommand[list[McpServer]]):
    """Return the user's MCP servers (tools ride the eager relationship)."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], *, user_id: UUID) -> None:
        """Store the sessionmaker and the owner."""
        self._sessionmaker = sessionmaker
        self._user_id = user_id

    async def run(self) -> list[McpServer]:
        """List the user's servers."""
        async with self._sessionmaker() as session:
            return await McpServerRepo(session).get_list(
                FieldEquals(McpServer.user_id, self._user_id)
            )
