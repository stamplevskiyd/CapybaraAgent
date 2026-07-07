"""Thin adapter over pydantic-ai's MCP client (remote HTTP/SSE transport only).

Every pydantic-ai MCP call is localised here so the rest of the app depends on this
small, stable interface rather than the library's evolving API. Remote transport only —
no stdio/subprocess in this slice.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic_ai.mcp import MCPToolset, StreamableHttpTransport  # type: ignore[attr-defined]
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import AbstractToolset

#: Bound the connect/handshake so a dead server can't hang attach/refresh/turns.
_INIT_TIMEOUT_SECONDS = 10.0

#: Exception types that mean "the server could not be reached" (vs. a protocol error).
_UNREACHABLE = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    ConnectionError,
    TimeoutError,
)


@dataclass(frozen=True)
class DiscoveredTool:
    """A tool reported by an MCP server's ``tools/list``."""

    name: str
    description: str | None
    input_schema: dict[str, Any] | None


class McpUnreachableError(Exception):
    """Raised when an MCP server cannot be reached (connection refused/timeout)."""


class McpProtocolError(Exception):
    """Raised when a server answered but the handshake or ``tools/list`` failed.

    This covers a wrong URL, a non-MCP endpoint, or rejected auth — an actionable
    configuration problem rather than an outage.
    """


def _flatten(exc: BaseException) -> Iterator[BaseException]:
    """Yield leaf exceptions, descending into ExceptionGroups (anyio wraps errors)."""
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            yield from _flatten(sub)
    else:
        yield exc


def _classify(exc: BaseException) -> Exception:
    """Map a raw pydantic-ai/MCP failure to an unreachable- or protocol-error."""
    if any(isinstance(leaf, _UNREACHABLE) for leaf in _flatten(exc)):
        return McpUnreachableError(str(exc))
    return McpProtocolError(str(exc))


def _raw_toolset(url: str, headers: dict[str, str], *, prefix_id: str | None = None) -> MCPToolset:
    """Build an unfiltered MCPToolset for *url*/*headers* (headers omitted when empty)."""
    transport = StreamableHttpTransport(url=url, headers=headers or None)
    return MCPToolset(transport, id=prefix_id, init_timeout=_INIT_TIMEOUT_SECONDS)


async def discover(url: str, headers: dict[str, str]) -> list[DiscoveredTool]:
    """Connect to the MCP server and return its advertised tools.

    Opens a session only for the duration of the call (handshake + ``tools/list``), then
    closes it.

    Raises:
        McpUnreachableError: If the server cannot be reached.
        McpProtocolError: If the server answered but the handshake/list failed.
    """
    toolset = _raw_toolset(url, headers)
    try:
        async with toolset:
            raw = await toolset.list_tools()
    except Exception as exc:  # noqa: BLE001 — re-raised as a classified adapter error
        raise _classify(exc) from exc
    return [
        DiscoveredTool(
            name=tool.name,
            description=getattr(tool, "description", None),
            input_schema=getattr(tool, "inputSchema", None),
        )
        for tool in raw
    ]


def build_toolset(
    url: str, headers: dict[str, str], enabled_tools: set[str], prefix: str
) -> AbstractToolset[None]:
    """Return an agent-ready toolset exposing only *enabled_tools*, namespaced by *prefix*.

    The filter matches on the server's original tool names (applied before prefixing);
    pydantic-ai then exposes each kept tool to the model as ``{prefix}_{tool}`` so names
    never collide across servers or with built-in tools. The MCP session is opened lazily
    by pydantic-ai for the duration of the agent run, not here.
    """
    enabled = set(enabled_tools)

    def _keep(_ctx: object, tool_def: ToolDefinition) -> bool:
        return tool_def.name in enabled

    toolset = _raw_toolset(url, headers, prefix_id=prefix)
    return toolset.filtered(_keep).prefixed(prefix)
