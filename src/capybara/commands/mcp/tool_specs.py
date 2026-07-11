"""Assemble per-turn tool specs from a user's enabled MCP servers."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.agent.deep_runtime import McpServerSpec
from capybara.commands.base import BaseCommand
from capybara.commands.mcp.utils import slugify
from capybara.db.models import McpServer
from capybara.filters import FieldEquals
from capybara.repositories.mcp_repo import McpServerRepo


class ListEnabledToolSpecs(BaseCommand[list[McpServerSpec]]):
    """Return LangChain-ready specs for the user's enabled servers (enabled tools only).

    No reachability preflight happens here: the DeepAgents loader connects when it
    builds the tools, so that connect doubles as the preflight and a dead server is
    dropped there.
    """

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], *, user_id: UUID) -> None:
        """Store the sessionmaker and the owner."""
        self._sessionmaker = sessionmaker
        self._user_id = user_id

    async def run(self) -> list[McpServerSpec]:
        """Build one spec per enabled server, filtered to its enabled tools."""
        async with self._sessionmaker() as session:
            servers = await McpServerRepo(session).get_list(
                FieldEquals(McpServer.user_id, self._user_id),
                FieldEquals(McpServer.enabled, True),
            )
            return [
                McpServerSpec(
                    prefix=slugify(server.name),
                    url=server.url,
                    headers=dict(server.headers),
                    enabled_tools=frozenset(tool.name for tool in server.tools if tool.enabled),
                )
                for server in servers
            ]
