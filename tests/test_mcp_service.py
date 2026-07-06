"""Tests for McpService against real Postgres, with the MCP adapter mocked."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.agent import mcp as mcp_adapter
from capybara.agent.mcp import DiscoveredTool, McpUnreachableError
from capybara.services.mcp_service import McpService

pytestmark = pytest.mark.asyncio


def _maker(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    """A sessionmaker that always hands back the test's transactional session."""
    from contextlib import asynccontextmanager

    class _Maker:
        def __call__(self):  # type: ignore[no-untyped-def]
            @asynccontextmanager
            async def _cm():  # type: ignore[no-untyped-def]
                yield session

            return _cm()

    return _Maker()  # type: ignore[return-value]


async def test_attach_persists_server_and_tools(
    session: AsyncSession, make_user, monkeypatch: pytest.MonkeyPatch  # type: ignore[no-untyped-def]
) -> None:
    """attach discovers tools and stores the server + enabled tools."""
    user = await make_user(session)

    async def fake_discover(url, headers):  # type: ignore[no-untyped-def]
        return [DiscoveredTool("turn_on", "d", {}), DiscoveredTool("turn_off", None, None)]

    monkeypatch.setattr(mcp_adapter, "discover", fake_discover)
    service = McpService(_maker(session))

    server, tools = await service.attach(user.id, "home", "http://ha/mcp", {"X-Api-Key": "k"})

    assert server.name == "home"
    assert server.last_connected_at is not None
    assert {t.name for t in tools} == {"turn_on", "turn_off"}
    assert all(t.enabled for t in tools)


async def test_attach_unreachable_persists_nothing(
    session: AsyncSession, make_user, monkeypatch: pytest.MonkeyPatch  # type: ignore[no-untyped-def]
) -> None:
    """A failed attach raises and writes no server row."""
    user = await make_user(session)

    async def boom(url, headers):  # type: ignore[no-untyped-def]
        raise McpUnreachableError("refused")

    monkeypatch.setattr(mcp_adapter, "discover", boom)
    service = McpService(_maker(session))

    with pytest.raises(McpUnreachableError):
        await service.attach(user.id, "home", "http://ha/mcp", {})
    assert await service.list_servers(user.id) == []


async def test_set_tool_enabled_and_build_toolsets(
    session: AsyncSession, make_user, monkeypatch: pytest.MonkeyPatch  # type: ignore[no-untyped-def]
) -> None:
    """Disabling a tool drops it; build_toolsets includes only reachable enabled servers."""
    user = await make_user(session)

    async def fake_discover(url, headers):  # type: ignore[no-untyped-def]
        return [DiscoveredTool("turn_on", "d", {}), DiscoveredTool("turn_off", None, None)]

    built: list = []

    def fake_build(url, headers, enabled_tools, prefix):  # type: ignore[no-untyped-def]
        built.append((prefix, set(enabled_tools)))
        return object()

    monkeypatch.setattr(mcp_adapter, "discover", fake_discover)
    monkeypatch.setattr(mcp_adapter, "build_toolset", fake_build)
    service = McpService(_maker(session))

    server, tools = await service.attach(user.id, "home", "http://ha/mcp", {})
    off = next(t for t in tools if t.name == "turn_off")
    await service.set_tool_enabled(user.id, server.id, off.id, enabled=False)

    toolsets = await service.build_toolsets(user.id)

    assert len(toolsets) == 1
    assert built == [("home", {"turn_on"})]  # only the enabled tool


async def test_build_toolsets_skips_unreachable(
    session: AsyncSession, make_user, monkeypatch: pytest.MonkeyPatch  # type: ignore[no-untyped-def]
) -> None:
    """A server unreachable at turn time is skipped (fail-open), not raised."""
    user = await make_user(session)

    async def fake_discover_ok(url, headers):  # type: ignore[no-untyped-def]
        return [DiscoveredTool("turn_on", "d", {})]

    monkeypatch.setattr(mcp_adapter, "discover", fake_discover_ok)
    service = McpService(_maker(session))
    await service.attach(user.id, "home", "http://ha/mcp", {})

    async def now_unreachable(url, headers):  # type: ignore[no-untyped-def]
        raise McpUnreachableError("gone")

    monkeypatch.setattr(mcp_adapter, "discover", now_unreachable)

    toolsets = await service.build_toolsets(user.id)
    assert toolsets == []  # skipped, no exception


async def test_refresh_preserves_enabled_flags(
    session: AsyncSession, make_user, monkeypatch: pytest.MonkeyPatch  # type: ignore[no-untyped-def]
) -> None:
    """refresh keeps a tool's enabled flag by name and adds/removes tools."""
    user = await make_user(session)

    async def discover_v1(url, headers):  # type: ignore[no-untyped-def]
        return [DiscoveredTool("turn_on", "d", {}), DiscoveredTool("turn_off", None, None)]

    monkeypatch.setattr(mcp_adapter, "discover", discover_v1)
    service = McpService(_maker(session))
    server, tools = await service.attach(user.id, "home", "http://ha/mcp", {})
    off = next(t for t in tools if t.name == "turn_off")
    await service.set_tool_enabled(user.id, server.id, off.id, enabled=False)

    async def discover_v2(url, headers):  # type: ignore[no-untyped-def]
        # turn_on stays, turn_off stays (disabled must persist), lock is new
        return [
            DiscoveredTool("turn_on", "d", {}),
            DiscoveredTool("turn_off", None, None),
            DiscoveredTool("lock", "new", {}),
        ]

    monkeypatch.setattr(mcp_adapter, "discover", discover_v2)
    refreshed = await service.refresh(user.id, server.id)
    assert refreshed is not None
    _server, refreshed_tools = refreshed
    by_name = {t.name: t for t in refreshed_tools}
    assert set(by_name) == {"turn_on", "turn_off", "lock"}
    assert by_name["turn_off"].enabled is False  # preserved
    assert by_name["lock"].enabled is True  # new default
