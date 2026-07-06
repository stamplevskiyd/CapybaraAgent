"""MCP service: attach/refresh/CRUD/curation of servers, and per-turn toolset assembly."""

import logging
import re
from datetime import UTC, datetime
from uuid import UUID

from pydantic_ai.toolsets import AbstractToolset
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.agent import mcp as mcp_adapter
from capybara.agent.mcp import McpProtocolError, McpUnreachableError
from capybara.db.models import McpServer, McpTool
from capybara.filters import FieldEquals
from capybara.repositories.mcp_repo import McpServerRepo, McpToolRepo

logger = logging.getLogger(__name__)


def _slug(name: str) -> str:
    """Derive a tool-name prefix from a server name (lowercase alnum, ``_``-joined)."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or "mcp"


class McpService:
    """Orchestrate MCP servers: discovery, persistence, curation, and toolset assembly.

    Owns short-lived sessions from the app-wide sessionmaker (never borrows a request
    session), so it is safe to use from both routes and a chat turn.
    """

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Store the app-wide sessionmaker."""
        self._sessionmaker = sessionmaker

    async def _load(
        self, session: AsyncSession, user_id: UUID, server_id: UUID
    ) -> tuple[McpServer, list[McpTool]] | None:
        """Return a user-owned server and its tools, or None if not found/owned."""
        server = await McpServerRepo(session).get(server_id)
        if server is None or server.user_id != user_id:
            return None
        tools = await McpToolRepo(session).list_for_server(server_id)
        return server, tools

    async def list_servers(self, user_id: UUID) -> list[tuple[McpServer, list[McpTool]]]:
        """Return the user's servers, each paired with its tools."""
        async with self._sessionmaker() as session:
            servers = await McpServerRepo(session).list(FieldEquals(McpServer.user_id, user_id))
            trepo = McpToolRepo(session)
            return [(s, await trepo.list_for_server(s.id)) for s in servers]

    async def get_server(
        self, user_id: UUID, server_id: UUID
    ) -> tuple[McpServer, list[McpTool]] | None:
        """Return a user-owned server and its tools, or None."""
        async with self._sessionmaker() as session:
            return await self._load(session, user_id, server_id)

    async def attach(
        self, user_id: UUID, name: str, url: str, headers: dict[str, str]
    ) -> tuple[McpServer, list[McpTool]]:
        """Discover *url*'s tools and persist the server + tools (all enabled).

        Raises:
            McpUnreachableError: If the server cannot be reached.
            McpProtocolError: If the handshake/list failed.
        """
        discovered = await mcp_adapter.discover(url, headers)  # raises → route maps to HTTP
        async with self._sessionmaker() as session:
            repo = McpServerRepo(session)
            trepo = McpToolRepo(session)
            server = await repo.create(
                user_id=user_id,
                name=name,
                url=url,
                headers=headers,
                enabled=True,
                last_connected_at=datetime.now(UTC),
                last_error=None,
            )
            tools = [
                await trepo.create(
                    server_id=server.id,
                    name=d.name,
                    description=d.description,
                    input_schema=d.input_schema,
                    enabled=True,
                )
                for d in discovered
            ]
            await session.commit()
            await session.refresh(server)
            for tool in tools:
                await session.refresh(tool)
            return server, tools

    async def update_server(
        self,
        user_id: UUID,
        server_id: UUID,
        *,
        name: str | None = None,
        url: str | None = None,
        headers: dict[str, str] | None = None,
        enabled: bool | None = None,
    ) -> tuple[McpServer, list[McpTool]] | None:
        """Update mutable server fields; return the server+tools, or None if not owned."""
        fields: dict[str, object] = {}
        if name is not None:
            fields["name"] = name
        if url is not None:
            fields["url"] = url
        if headers is not None:
            fields["headers"] = headers
        if enabled is not None:
            fields["enabled"] = enabled
        async with self._sessionmaker() as session:
            repo = McpServerRepo(session)
            server = await repo.get(server_id)
            if server is None or server.user_id != user_id:
                return None
            if fields:
                await repo.update(server, **fields)
                await session.commit()
            return await self._load(session, user_id, server_id)

    async def delete_server(self, user_id: UUID, server_id: UUID) -> bool:
        """Delete a user-owned server (cascades its tools); return whether it existed."""
        async with self._sessionmaker() as session:
            repo = McpServerRepo(session)
            server = await repo.get(server_id)
            if server is None or server.user_id != user_id:
                return False
            await repo.delete(server)
            await session.commit()
            return True

    async def refresh(
        self, user_id: UUID, server_id: UUID
    ) -> tuple[McpServer, list[McpTool]] | None:
        """Re-discover a server's tools, preserving each tool's enabled flag by name.

        Returns None if the server is not owned. On a discovery failure, records
        ``last_error`` and re-raises (an explicit action → actionable HTTP error).
        """
        async with self._sessionmaker() as session:
            loaded = await self._load(session, user_id, server_id)
            if loaded is None:
                return None
            server, _ = loaded
            url, headers = server.url, dict(server.headers)
        try:
            discovered = await mcp_adapter.discover(url, headers)
        except (McpUnreachableError, McpProtocolError) as exc:
            async with self._sessionmaker() as session:
                repo = McpServerRepo(session)
                server_row: McpServer | None = await repo.get(server_id)
                if server_row is not None:
                    await repo.update(server_row, last_error=str(exc))
                    await session.commit()
            raise
        async with self._sessionmaker() as session:
            repo = McpServerRepo(session)
            trepo = McpToolRepo(session)
            existing = {t.name: t for t in await trepo.list_for_server(server_id)}
            new_names = {d.name for d in discovered}
            for name, tool in existing.items():
                if name not in new_names:
                    await trepo.delete(tool)
            for d in discovered:
                if d.name in existing:
                    await trepo.update(
                        existing[d.name], description=d.description, input_schema=d.input_schema
                    )
                else:
                    await trepo.create(
                        server_id=server_id,
                        name=d.name,
                        description=d.description,
                        input_schema=d.input_schema,
                        enabled=True,
                    )
            refreshed_server: McpServer | None = await repo.get(server_id)
            assert refreshed_server is not None  # loaded above under the same ownership check
            await repo.update(refreshed_server, last_connected_at=datetime.now(UTC), last_error=None)
            await session.commit()
            return await self._load(session, user_id, server_id)

    async def set_tool_enabled(
        self, user_id: UUID, server_id: UUID, tool_id: UUID, *, enabled: bool
    ) -> McpTool | None:
        """Toggle a tool's enabled flag; return the tool, or None if not owned/found."""
        async with self._sessionmaker() as session:
            server = await McpServerRepo(session).get(server_id)
            if server is None or server.user_id != user_id:
                return None
            trepo = McpToolRepo(session)
            tool = await trepo.get(tool_id)
            if tool is None or tool.server_id != server_id:
                return None
            tool = await trepo.update(tool, enabled=enabled)
            await session.commit()
            await session.refresh(tool)
            return tool

    async def build_toolsets(self, user_id: UUID) -> list[AbstractToolset[None]]:
        """Build agent-ready toolsets for the user's enabled servers (enabled tools only).

        Fail-open: each enabled server is reachability-checked via ``discover``; an
        unreachable server is logged and skipped so a dead server never breaks the turn.

        NOTE (known slice-A inefficiency): this reachability check opens a session, and
        pydantic-ai opens another when the agent actually runs the toolset — two
        handshakes per server per turn. A persistent connection pool is a later slice.
        """
        async with self._sessionmaker() as session:
            servers = await McpServerRepo(session).list(
                FieldEquals(McpServer.user_id, user_id), FieldEquals(McpServer.enabled, True)
            )
            trepo = McpToolRepo(session)
            specs = [
                (
                    s.name,
                    s.url,
                    dict(s.headers),
                    {t.name for t in await trepo.list_for_server(s.id) if t.enabled},
                )
                for s in servers
            ]
        toolsets: list[AbstractToolset[None]] = []
        for name, url, headers, enabled_names in specs:
            if not enabled_names:
                continue
            try:
                await mcp_adapter.discover(url, headers)
            except (McpUnreachableError, McpProtocolError):
                logger.warning("MCP server %r unreachable this turn; skipping its tools", name)
                continue
            toolsets.append(mcp_adapter.build_toolset(url, headers, enabled_names, _slug(name)))
        return toolsets
