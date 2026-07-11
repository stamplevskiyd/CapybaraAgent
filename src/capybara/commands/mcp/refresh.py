"""Re-discover an MCP server's tools, preserving curation."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.agent import mcp as mcp_adapter
from capybara.agent.mcp import McpProtocolError, McpUnreachableError
from capybara.commands.base import BaseCommand
from capybara.commands.mcp.utils import owned_server
from capybara.db.models import McpServer, McpTool
from capybara.repositories.mcp_repo import McpServerRepo, McpToolRepo


class RefreshMcpServer(BaseCommand[McpServer | None]):
    """Re-discover a server's tools, preserving each tool's enabled flag by name."""

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
        """Re-discover and diff the tool set; record ``last_error`` on failure.

        Returns None if the server is not owned. On a discovery failure, records
        ``last_error`` and re-raises (an explicit action → actionable HTTP error).
        """
        # Read connection details on a short session; the discovery round-trip then
        # runs with no DB connection held.
        async with self._sessionmaker() as session:
            server = await owned_server(session, self._user_id, self._server_id)
            if server is None:
                return None
            url, headers = server.url, dict(server.headers)
        try:
            discovered = await mcp_adapter.discover(url, headers)
        except (McpUnreachableError, McpProtocolError) as exc:
            async with self._sessionmaker() as session:
                repo = McpServerRepo(session)
                failed = await repo.get(self._server_id)
                if failed is not None:
                    await repo.update(failed, last_error=str(exc))
                    await session.commit()
            raise
        async with self._sessionmaker() as session:
            server = await owned_server(session, self._user_id, self._server_id)
            if server is None:
                return None
            existing = {tool.name: tool for tool in server.tools}
            new_names = {d.name for d in discovered}
            trepo = McpToolRepo(session)
            for name, tool in existing.items():
                if name not in new_names:
                    server.tools.remove(tool)  # delete-orphan drops the row
            for d in discovered:
                if d.name in existing:
                    await trepo.update(
                        existing[d.name], description=d.description, input_schema=d.input_schema
                    )
                else:
                    server.tools.append(
                        McpTool(
                            name=d.name,
                            description=d.description,
                            input_schema=d.input_schema,
                            enabled=True,
                        )
                    )
            server = await McpServerRepo(session).update(
                server, last_connected_at=datetime.now(UTC), last_error=None
            )
            await session.commit()
            await session.refresh(server)  # reload updated_at expired by the UPDATE flush
            return server
