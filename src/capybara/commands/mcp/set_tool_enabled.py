"""Toggle one MCP tool's enabled flag (curation)."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.commands.base import BaseCommand
from capybara.commands.mcp.utils import owned_server
from capybara.db.models import McpTool
from capybara.repositories.mcp_repo import McpToolRepo


class SetMcpToolEnabled(BaseCommand[McpTool | None]):
    """Toggle a tool's enabled flag; only enabled tools are offered to the agent."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        user_id: UUID,
        server_id: UUID,
        tool_id: UUID,
        enabled: bool,
    ) -> None:
        """Store the sessionmaker, the tool's address, and the new flag."""
        self._sessionmaker = sessionmaker
        self._user_id = user_id
        self._server_id = server_id
        self._tool_id = tool_id
        self._enabled = enabled

    async def run(self) -> McpTool | None:
        """Flip the flag; return the tool, or None if the server/tool is not owned."""
        async with self._sessionmaker() as session:
            server = await owned_server(session, self._user_id, self._server_id)
            if server is None:
                return None
            tool = next((t for t in server.tools if t.id == self._tool_id), None)
            if tool is None:
                return None
            tool = await McpToolRepo(session).update(tool, enabled=self._enabled)
            await session.commit()
            return tool
