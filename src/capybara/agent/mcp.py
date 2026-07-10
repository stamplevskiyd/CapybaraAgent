"""Thin adapter over the MCP client for tool discovery (remote streamable-HTTP only).

Every MCP call is localised here so the rest of the app depends on this small, stable
interface rather than the library's evolving API. Remote transport only — no
stdio/subprocess in this slice.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx
from langchain_mcp_adapters.sessions import StreamableHttpConnection, create_session

#: Bound the connect/handshake so a dead server can't hang attach/refresh/turns.
INIT_TIMEOUT_SECONDS = 10.0

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
    """Map a raw MCP failure to an unreachable- or protocol-error."""
    if any(isinstance(leaf, _UNREACHABLE) for leaf in _flatten(exc)):
        return McpUnreachableError(str(exc))
    return McpProtocolError(str(exc))


def streamable_http_connection(url: str, headers: dict[str, str]) -> StreamableHttpConnection:
    """Build a streamable-HTTP MCP connection for *url*/*headers* (headers omitted if empty).

    Shared by discovery (here) and the per-turn tool loader so both use the same
    transport settings and init timeout.
    """
    return {
        "transport": "streamable_http",
        "url": url,
        "headers": headers or None,
        "timeout": INIT_TIMEOUT_SECONDS,
    }


async def discover(url: str, headers: dict[str, str]) -> list[DiscoveredTool]:
    """Connect to the MCP server and return its advertised tools.

    Opens a session only for the duration of the call (handshake + ``tools/list``), then
    closes it.

    Raises:
        McpUnreachableError: If the server cannot be reached.
        McpProtocolError: If the server answered but the handshake/list failed.
    """
    try:
        async with create_session(streamable_http_connection(url, headers)) as session:
            await session.initialize()
            result = await session.list_tools()
    except Exception as exc:  # noqa: BLE001 — re-raised as a classified adapter error
        raise _classify(exc) from exc
    return [
        DiscoveredTool(
            name=tool.name,
            description=tool.description,
            input_schema=tool.inputSchema,
        )
        for tool in result.tools
    ]
