"""LangChain tool factories that expose Capybara services to the DeepAgents runtime.

Ports the pydantic-ai tool seam (``capybara.services.memory_tools``) to LangChain
``BaseTool`` instances the DeepAgents graph can register. The formatting/untrusted-memory
boundary is reused unchanged so recalled facts keep their prompt-injection guard.
"""

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol
from uuid import UUID

from langchain_core.tools import BaseTool, StructuredTool
from langchain_mcp_adapters.sessions import StreamableHttpConnection
from langchain_mcp_adapters.tools import load_mcp_tools

from capybara.agent.deep_runtime import McpServerSpec, ToolLike, ToolProvider
from capybara.db.models import Fact
from capybara.services.memory_tools import format_facts

logger = logging.getLogger(__name__)

#: Bound the MCP connect/list so a dead server can't stall a turn.
_MCP_INIT_TIMEOUT_SECONDS = 10.0

#: Resolve the user whose tools this turn should expose, or None when unauthenticated.
UserIdGetter = Callable[[], UUID | None]


class SupportsRecall(Protocol):
    """Subset of ``MemoryService`` needed to build the recall tool."""

    async def recall(self, user_id: UUID, query: str) -> list[Fact]:
        """Return facts semantically nearest to *query* for *user_id*."""
        ...


def make_recall_tool(memory_service: SupportsRecall, user_id: UUID) -> BaseTool:
    """Build a LangChain recall tool closed over the service and user.

    The service and user are captured in the closure so the tool takes only a ``query``
    argument, letting it drop into the DeepAgents graph's tool list unchanged. Results pass
    through ``format_facts`` so recalled user text stays wrapped in its untrusted-memory
    boundary.
    """

    async def recall(query: str) -> str:
        """Search the user's long-term memory for relevant facts."""
        return format_facts(await memory_service.recall(user_id, query))

    return StructuredTool.from_function(
        coroutine=recall,
        name="recall",
        description="Search the user's long-term memory for relevant facts.",
    )


class MemoryToolProvider:
    """Hand the DeepAgents runner the current user's memory tools, rebuilt each turn.

    Memory is per-user, so the tool must bind to whoever the turn belongs to. The user id
    is resolved lazily via *get_user_id* (the Chainlit session) rather than captured once,
    and an unresolved user yields no tools — a turn never reaches another user's memory.
    """

    def __init__(self, memory_service: SupportsRecall | None, *, get_user_id: UserIdGetter) -> None:
        """Store the memory service and the per-turn user resolver."""
        self._memory_service = memory_service
        self._get_user_id = get_user_id

    async def tools_for(self, thread_id: str) -> Sequence[ToolLike]:
        """Return the recall tool bound to this turn's user, or nothing if unresolved."""
        user_id = self._get_user_id()
        if user_id is None or self._memory_service is None:
            return []
        return [make_recall_tool(self._memory_service, user_id)]


#: Load one server's LangChain tools (prefixed); raises when the server is unreachable.
McpToolLoader = Callable[[McpServerSpec], Awaitable[list[BaseTool]]]


async def _load_server_tools(spec: McpServerSpec) -> list[BaseTool]:
    """Connect to *spec*'s MCP server and return its tools, each prefixed by the slug."""
    connection: StreamableHttpConnection = {
        "transport": "streamable_http",
        "url": spec.url,
        "headers": spec.headers or None,
        "timeout": _MCP_INIT_TIMEOUT_SECONDS,
    }
    return await load_mcp_tools(
        None, connection=connection, server_name=spec.prefix, tool_name_prefix=True
    )


async def build_mcp_tools(
    specs: Sequence[McpServerSpec], *, loader: McpToolLoader = _load_server_tools
) -> list[BaseTool]:
    """Build LangChain tools for the given MCP server specs, enabled tools only.

    Fail-open: connecting to a server is also its reachability preflight, so a server that
    is unreachable (or errors while listing) is logged and skipped rather than breaking the
    turn. Tools are filtered to each server's enabled set by their prefixed names.
    """
    tools: list[BaseTool] = []
    for spec in specs:
        if not spec.enabled_tools:
            continue
        try:
            loaded = await loader(spec)
        except Exception:  # noqa: BLE001 — fail open: a dead server must not break the reply
            logger.warning("MCP server %r unreachable this turn; skipping its tools", spec.prefix)
            continue
        allowed = {f"{spec.prefix}_{name}" for name in spec.enabled_tools}
        tools.extend(tool for tool in loaded if tool.name in allowed)
    return tools


class SupportsMcpSpecs(Protocol):
    """Subset of ``McpService`` needed to build MCP tools for a turn."""

    async def enabled_tool_specs(self, user_id: UUID) -> Sequence[McpServerSpec]:
        """Return specs for the user's enabled servers (enabled tools only)."""
        ...


class McpToolProvider:
    """Hand the runner the current user's MCP tools, reconnected each turn.

    MCP tools are per-user and their servers can come and go, so they are resolved lazily:
    an unresolved user yields nothing, and unreachable servers are dropped by
    ``build_mcp_tools`` rather than failing the turn.
    """

    def __init__(self, mcp_service: SupportsMcpSpecs | None, *, get_user_id: UserIdGetter) -> None:
        """Store the MCP service and the per-turn user resolver."""
        self._mcp_service = mcp_service
        self._get_user_id = get_user_id

    async def tools_for(self, thread_id: str) -> Sequence[ToolLike]:
        """Return the current user's MCP tools, or nothing if unresolved."""
        user_id = self._get_user_id()
        if user_id is None or self._mcp_service is None:
            return []
        specs = await self._mcp_service.enabled_tool_specs(user_id)
        return list(await build_mcp_tools(specs))


class CompositeToolProvider:
    """Combine several tool providers behind the runner's single-provider seam."""

    def __init__(self, *providers: ToolProvider) -> None:
        """Store the child providers to combine, in order."""
        self._providers = providers

    async def tools_for(self, thread_id: str) -> Sequence[ToolLike]:
        """Return every child provider's tools for this turn, in order."""
        tools: list[ToolLike] = []
        for provider in self._providers:
            tools.extend(await provider.tools_for(thread_id))
        return tools
