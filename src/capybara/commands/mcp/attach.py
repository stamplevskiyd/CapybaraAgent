"""Attach an MCP server: discover its tools and persist the pair."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.agent import mcp as mcp_adapter
from capybara.commands.base import BaseCommand
from capybara.db.models import McpServer, McpTool
from capybara.repositories.mcp_repo import McpServerRepo


class AttachMcpServer(BaseCommand[McpServer]):
    """Discover the server's tools and persist the server + tools (all enabled)."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        user_id: UUID,
        name: str,
        url: str,
        headers: dict[str, str],
    ) -> None:
        """Store the sessionmaker and the connection details to attach."""
        self._sessionmaker = sessionmaker
        self._user_id = user_id
        self._name = name
        self._url = url
        self._headers = headers

    async def run(self) -> McpServer:
        """Discover tools (the connect doubles as validation), then persist.

        Raises:
            McpUnreachableError: If the server cannot be reached.
            McpProtocolError: If the handshake/list failed.
        """
        discovered = await mcp_adapter.discover(self._url, self._headers)
        async with self._sessionmaker() as session:
            server = await McpServerRepo(session).create(
                user_id=self._user_id,
                name=self._name,
                url=self._url,
                headers=self._headers,
                enabled=True,
                last_connected_at=datetime.now(UTC),
                last_error=None,
                tools=[
                    McpTool(
                        name=d.name,
                        description=d.description,
                        input_schema=d.input_schema,
                        enabled=True,
                    )
                    for d in discovered
                ],
            )
            await session.commit()
            return server
