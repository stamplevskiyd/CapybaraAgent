"""MCP service: attach/refresh/CRUD/curation of servers, and per-turn tool-spec assembly."""

import re
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.agent import mcp as mcp_adapter
from capybara.agent.deep_runtime import McpServerSpec
from capybara.agent.mcp import McpProtocolError, McpUnreachableError
from capybara.db.models import McpServer, McpTool
from capybara.repositories.mcp_repo import McpServerRepo, McpToolRepo


def _slug(name: str) -> str:
    """Derive a tool-name prefix from a server name (lowercase alnum, ``_``-joined)."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or "mcp"


class McpService:
    """Orchestrate MCP servers: discovery, persistence, curation, and tool-spec assembly.

    Owns short-lived sessions from the app-wide sessionmaker (never borrows a request
    session), so it is safe to use from both routes and a chat turn. Servers carry their
    tools via the eager ``McpServer.tools`` relationship.
    """

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Store the app-wide sessionmaker."""
        self._sessionmaker = sessionmaker

    async def _owned(
        self, session: AsyncSession, user_id: UUID, server_id: UUID
    ) -> McpServer | None:
        """Return the server if it exists and belongs to *user_id*, else None."""
        server = await McpServerRepo(session).get(server_id)
        if server is None or server.user_id != user_id:
            return None
        return server

    async def list_servers(self, user_id: UUID) -> list[McpServer]:
        """Return the user's servers (tools included)."""
        async with self._sessionmaker() as session:
            return await McpServerRepo(session).list(McpServer.user_id == user_id)

    async def get_server(self, user_id: UUID, server_id: UUID) -> McpServer | None:
        """Return a user-owned server, or None."""
        async with self._sessionmaker() as session:
            return await self._owned(session, user_id, server_id)

    async def attach(
        self, user_id: UUID, name: str, url: str, headers: dict[str, str]
    ) -> McpServer:
        """Discover *url*'s tools and persist the server + tools (all enabled).

        Raises:
            McpUnreachableError: If the server cannot be reached.
            McpProtocolError: If the handshake/list failed.
        """
        discovered = await mcp_adapter.discover(url, headers)  # raises → route maps to HTTP
        async with self._sessionmaker() as session:
            server = await McpServerRepo(session).create(
                user_id=user_id,
                name=name,
                url=url,
                headers=headers,
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

    async def update_server(
        self,
        user_id: UUID,
        server_id: UUID,
        *,
        name: str | None = None,
        url: str | None = None,
        headers: dict[str, str] | None = None,
        enabled: bool | None = None,
    ) -> McpServer | None:
        """Update mutable server fields; return the server, or None if not owned."""
        patch = {"name": name, "url": url, "headers": headers, "enabled": enabled}
        fields = {key: value for key, value in patch.items() if value is not None}
        async with self._sessionmaker() as session:
            server = await self._owned(session, user_id, server_id)
            if server is None:
                return None
            if fields:
                server = await McpServerRepo(session).update(server, **fields)
                await session.commit()
                # The UPDATE flush expires updated_at (onupdate); reload before the session
                # closes so serialization does not trigger a sync lazy load.
                await session.refresh(server)
            return server

    async def delete_server(self, user_id: UUID, server_id: UUID) -> bool:
        """Delete a user-owned server (cascades its tools); return whether it existed."""
        async with self._sessionmaker() as session:
            server = await self._owned(session, user_id, server_id)
            if server is None:
                return False
            await McpServerRepo(session).delete(server)
            await session.commit()
            return True

    async def refresh(self, user_id: UUID, server_id: UUID) -> McpServer | None:
        """Re-discover a server's tools, preserving each tool's enabled flag by name.

        Returns None if the server is not owned. On a discovery failure, records
        ``last_error`` and re-raises (an explicit action → actionable HTTP error).
        """
        # Read connection details on a short session; the discovery round-trip then runs
        # with no DB connection held.
        async with self._sessionmaker() as session:
            server = await self._owned(session, user_id, server_id)
            if server is None:
                return None
            url, headers = server.url, dict(server.headers)
        try:
            discovered = await mcp_adapter.discover(url, headers)
        except (McpUnreachableError, McpProtocolError) as exc:
            async with self._sessionmaker() as session:
                repo = McpServerRepo(session)
                failed = await repo.get(server_id)
                if failed is not None:
                    await repo.update(failed, last_error=str(exc))
                    await session.commit()
            raise
        async with self._sessionmaker() as session:
            server = await self._owned(session, user_id, server_id)
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

    async def set_tool_enabled(
        self, user_id: UUID, server_id: UUID, tool_id: UUID, *, enabled: bool
    ) -> McpTool | None:
        """Toggle a tool's enabled flag (curation); return the tool, or None if not owned."""
        async with self._sessionmaker() as session:
            server = await self._owned(session, user_id, server_id)
            if server is None:
                return None
            tool = next((t for t in server.tools if t.id == tool_id), None)
            if tool is None:
                return None
            tool = await McpToolRepo(session).update(tool, enabled=enabled)
            await session.commit()
            return tool

    async def enabled_tool_specs(self, user_id: UUID) -> list[McpServerSpec]:
        """Return LangChain-ready specs for the user's enabled servers (enabled tools only).

        No reachability preflight happens here: the DeepAgents loader connects when it
        builds the tools, so that connect doubles as the preflight and a dead server is
        dropped there.
        """
        async with self._sessionmaker() as session:
            servers = await McpServerRepo(session).list(
                McpServer.user_id == user_id, McpServer.enabled.is_(True)
            )
            return [
                McpServerSpec(
                    prefix=_slug(server.name),
                    url=server.url,
                    headers=dict(server.headers),
                    enabled_tools=frozenset(tool.name for tool in server.tools if tool.enabled),
                )
                for server in servers
            ]
