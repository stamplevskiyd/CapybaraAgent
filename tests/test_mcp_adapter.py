"""Tests for the MCP discovery adapter, with the MCP client session mocked out."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

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


class _FakeSession:
    def __init__(self, tools: list[_FakeTool]) -> None:
        self._tools = tools

    async def initialize(self) -> None:
        return None

    async def list_tools(self) -> SimpleNamespace:
        return SimpleNamespace(tools=self._tools)


def _patch_session(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tools: list[_FakeTool] | None = None,
    enter_error: BaseException | None = None,
    list_error: BaseException | None = None,
    captured: dict | None = None,
) -> None:
    """Replace create_session with a fake async context manager yielding a fake session."""

    @asynccontextmanager
    async def fake_create_session(connection):  # type: ignore[no-untyped-def]
        if captured is not None:
            captured["connection"] = connection
        if enter_error is not None:
            raise enter_error
        session = _FakeSession(tools or [])
        if list_error is not None:
            session.list_tools = _raiser(list_error)  # type: ignore[method-assign]
        yield session

    monkeypatch.setattr(mcp_adapter, "create_session", fake_create_session)


def _raiser(exc: BaseException):  # type: ignore[no-untyped-def]
    async def _list_tools() -> SimpleNamespace:
        raise exc

    return _list_tools


@pytest.mark.asyncio
async def test_discover_maps_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """discover returns DiscoveredTool objects mapping name/description/input_schema."""
    captured: dict = {}
    _patch_session(
        monkeypatch,
        tools=[
            _FakeTool("turn_on", "Turn on", {"type": "object"}),
            _FakeTool("turn_off", None, None),
        ],
        captured=captured,
    )

    tools = await discover("http://ha/mcp", {"Authorization": "Bearer x"})

    assert tools == [
        DiscoveredTool(name="turn_on", description="Turn on", input_schema={"type": "object"}),
        DiscoveredTool(name="turn_off", description=None, input_schema=None),
    ]
    # Headers and URL are threaded into the streamable-HTTP connection.
    assert captured["connection"]["url"] == "http://ha/mcp"
    assert captured["connection"]["headers"] == {"Authorization": "Bearer x"}
    assert captured["connection"]["transport"] == "streamable_http"


@pytest.mark.asyncio
async def test_discover_connection_error_is_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """A connection failure surfaces as McpUnreachableError."""
    _patch_session(monkeypatch, enter_error=httpx.ConnectError("refused"))

    with pytest.raises(McpUnreachableError):
        await discover("http://ha/mcp", {})


@pytest.mark.asyncio
async def test_discover_other_error_is_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-connection failure surfaces as McpProtocolError."""
    _patch_session(monkeypatch, list_error=ValueError("bad handshake"))

    with pytest.raises(McpProtocolError):
        await discover("http://ha/mcp", {})


@pytest.mark.asyncio
async def test_discover_flattens_exception_group(monkeypatch: pytest.MonkeyPatch) -> None:
    """A connection error wrapped in an ExceptionGroup is still McpUnreachableError."""
    _patch_session(
        monkeypatch,
        enter_error=BaseExceptionGroup("grp", [httpx.ConnectError("refused")]),
    )

    with pytest.raises(McpUnreachableError):
        await discover("http://ha/mcp", {})
