"""Delete an MCP server (its tools cascade)."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.commands.base import BaseCommand
from capybara.commands.mcp.utils import owned_server
from capybara.repositories.mcp_repo import McpServerRepo


class DeleteMcpServer(BaseCommand[bool]):
    """Delete a user-owned server; the result reports whether it existed."""

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

    async def run(self) -> bool:
        """Delete the server if owned; return whether it existed."""
        async with self._sessionmaker() as session:
            server = await owned_server(session, self._user_id, self._server_id)
            if server is None:
                return False
            await McpServerRepo(session).delete(server)
            await session.commit()
            return True
