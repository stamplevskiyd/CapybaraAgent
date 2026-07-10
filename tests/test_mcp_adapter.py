"""Tests for the pydantic-ai MCP adapter, with MCPToolset mocked out."""

import httpx
import pytest

from capybara.agent import mcp as mcp_adapter
from capybara.agent.mcp import (
    DiscoveredTool,
    McpProtocolError,
    McpUnreachableError,
    discover,
)


class _FakeTool:
    def __init__(self, name: str, description: str | None, input_schema: dict | None) -> None:
        self.name = name
        self.description = description
        self.inputSchema = input_schema  # noqa: N815 — mirrors the MCP wire field name


class _FakeToolset:
    """Stand-in for pydantic-ai's MCPToolset: records construction, yields fake tools."""

    last_kwargs: dict = {}

    def __init__(self, transport, *, id=None, init_timeout=None):  # type: ignore[no-untyped-def]
        _FakeToolset.last_kwargs = {"transport": transport, "id": id}
        self._tools = [
            _FakeTool("turn_on", "Turn on", {"type": "object"}),
            _FakeTool("turn_off", None, None),
        ]
        self.filtered_with = None
        self.prefixed_with = None

    async def __aenter__(self):  # type: ignore[no-untyped-def]
        return self

    async def __aexit__(self, *exc):  # type: ignore[no-untyped-def]
        return False

    async def list_tools(self):  # type: ignore[no-untyped-def]
        return self._tools

    def filtered(self, fn):  # type: ignore[no-untyped-def]
        self.filtered_with = fn
        return self

    def prefixed(self, prefix):  # type: ignore[no-untyped-def]
        self.prefixed_with = prefix
        return self


@pytest.mark.asyncio
async def test_discover_maps_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """discover returns DiscoveredTool objects mapping name/description/input_schema."""
    monkeypatch.setattr(mcp_adapter, "MCPToolset", _FakeToolset)
    monkeypatch.setattr(mcp_adapter, "StreamableHttpTransport", lambda **kw: kw)

    tools = await discover("http://ha/mcp", {"Authorization": "Bearer x"})

    assert tools == [
        DiscoveredTool(name="turn_on", description="Turn on", input_schema={"type": "object"}),
        DiscoveredTool(name="turn_off", description=None, input_schema=None),
    ]
    # Headers are threaded into the transport.
    assert _FakeToolset.last_kwargs["transport"] == {
        "url": "http://ha/mcp",
        "headers": {"Authorization": "Bearer x"},
    }


@pytest.mark.asyncio
async def test_discover_connection_error_is_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """A connection failure surfaces as McpUnreachableError."""

    class _Boom(_FakeToolset):
        async def __aenter__(self):  # type: ignore[no-untyped-def]
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(mcp_adapter, "MCPToolset", _Boom)
    monkeypatch.setattr(mcp_adapter, "StreamableHttpTransport", lambda **kw: kw)

    with pytest.raises(McpUnreachableError):
        await discover("http://ha/mcp", {})


@pytest.mark.asyncio
async def test_discover_other_error_is_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-connection failure surfaces as McpProtocolError."""

    class _Boom(_FakeToolset):
        async def list_tools(self):  # type: ignore[no-untyped-def]
            raise ValueError("bad handshake")

    monkeypatch.setattr(mcp_adapter, "MCPToolset", _Boom)
    monkeypatch.setattr(mcp_adapter, "StreamableHttpTransport", lambda **kw: kw)

    with pytest.raises(McpProtocolError):
        await discover("http://ha/mcp", {})


@pytest.mark.asyncio
async def test_discover_flattens_exception_group(monkeypatch: pytest.MonkeyPatch) -> None:
    """A connection error wrapped in an ExceptionGroup is still McpUnreachableError."""

    class _Boom(_FakeToolset):
        async def __aenter__(self):  # type: ignore[no-untyped-def]
            raise BaseExceptionGroup("grp", [httpx.ConnectError("refused")])

    monkeypatch.setattr(mcp_adapter, "MCPToolset", _Boom)
    monkeypatch.setattr(mcp_adapter, "StreamableHttpTransport", lambda **kw: kw)

    with pytest.raises(McpUnreachableError):
        await discover("http://ha/mcp", {})
