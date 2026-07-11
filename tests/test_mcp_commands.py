"""Tests for the MCP commands against real Postgres, with the adapter mocked."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.agent import mcp as mcp_adapter
from capybara.agent.deep_tools import McpServerSpec
from capybara.agent.mcp import DiscoveredTool, McpUnreachableError
from capybara.commands.mcp.attach import AttachMcpServer
from capybara.commands.mcp.list_servers import ListMcpServers
from capybara.commands.mcp.refresh import RefreshMcpServer
from capybara.commands.mcp.set_tool_enabled import SetMcpToolEnabled
from capybara.commands.mcp.tool_specs import ListEnabledToolSpecs

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
    session: AsyncSession,
    make_user,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    """attach discovers tools and stores the server + enabled tools."""
    user = await make_user(session)

    async def fake_discover(url, headers):  # type: ignore[no-untyped-def]
        return [DiscoveredTool("turn_on", "d", {}), DiscoveredTool("turn_off", None, None)]

    monkeypatch.setattr(mcp_adapter, "discover", fake_discover)
    maker = _maker(session)

    server = await AttachMcpServer(
        maker, user_id=user.id, name="home", url="http://ha/mcp", headers={"X-Api-Key": "k"}
    ).execute()

    assert server.name == "home"
    assert server.last_connected_at is not None
    assert {t.name for t in server.tools} == {"turn_on", "turn_off"}
    assert all(t.enabled for t in server.tools)


async def test_attach_unreachable_persists_nothing(
    session: AsyncSession,
    make_user,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    """A failed attach raises and writes no server row."""
    user = await make_user(session)

    async def boom(url, headers):  # type: ignore[no-untyped-def]
        raise McpUnreachableError("refused")

    monkeypatch.setattr(mcp_adapter, "discover", boom)
    maker = _maker(session)

    with pytest.raises(McpUnreachableError):
        await AttachMcpServer(
            maker, user_id=user.id, name="home", url="http://ha/mcp", headers={}
        ).execute()
    assert await ListMcpServers(maker, user_id=user.id).execute() == []


async def test_enabled_tool_specs_returns_langchain_ready_specs(
    session: AsyncSession,
    make_user,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    """enabled_tool_specs yields one spec per enabled server, enabled tools only."""
    user = await make_user(session)

    async def fake_discover(url, headers):  # type: ignore[no-untyped-def]
        return [DiscoveredTool("turn_on", "d", {}), DiscoveredTool("turn_off", None, None)]

    monkeypatch.setattr(mcp_adapter, "discover", fake_discover)
    maker = _maker(session)
    server = await AttachMcpServer(
        maker, user_id=user.id, name="home", url="http://ha/mcp", headers={"X-Api-Key": "k"}
    ).execute()
    off = next(t for t in server.tools if t.name == "turn_off")
    await SetMcpToolEnabled(
        maker, user_id=user.id, server_id=server.id, tool_id=off.id, enabled=False
    ).execute()

    specs = await ListEnabledToolSpecs(maker, user_id=user.id).execute()

    assert specs == [
        McpServerSpec(
            prefix="home",
            url="http://ha/mcp",
            headers={"X-Api-Key": "k"},
            enabled_tools=frozenset({"turn_on"}),
        )
    ]


async def test_refresh_removes_tools_no_longer_reported(
    session: AsyncSession,
    make_user,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    """refresh drops tools no longer reported by the server, from both return value and DB."""
    user = await make_user(session, username="refresh_drop")

    async def discover_v1(url, headers):  # type: ignore[no-untyped-def]
        return [DiscoveredTool("turn_on", "d", {}), DiscoveredTool("turn_off", None, None)]

    monkeypatch.setattr(mcp_adapter, "discover", discover_v1)
    maker = _maker(session)
    server = await AttachMcpServer(
        maker, user_id=user.id, name="home", url="http://ha/mcp", headers={}
    ).execute()
    assert {t.name for t in server.tools} == {"turn_on", "turn_off"}

    async def discover_v2(url, headers):  # type: ignore[no-untyped-def]
        return [DiscoveredTool("turn_on", "d", {})]  # turn_off no longer reported

    monkeypatch.setattr(mcp_adapter, "discover", discover_v2)
    refreshed = await RefreshMcpServer(maker, user_id=user.id, server_id=server.id).execute()
    assert refreshed is not None
    assert {t.name for t in refreshed.tools} == {"turn_on"}  # turn_off gone from return value

    listed = await ListMcpServers(maker, user_id=user.id).execute()
    assert listed
    assert {t.name for t in listed[0].tools} == {"turn_on"}  # turn_off gone from the DB too


async def test_refresh_preserves_enabled_flags(
    session: AsyncSession,
    make_user,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    """refresh keeps a tool's enabled flag by name and adds/removes tools."""
    user = await make_user(session)

    async def discover_v1(url, headers):  # type: ignore[no-untyped-def]
        return [DiscoveredTool("turn_on", "d", {}), DiscoveredTool("turn_off", None, None)]

    monkeypatch.setattr(mcp_adapter, "discover", discover_v1)
    maker = _maker(session)
    server = await AttachMcpServer(
        maker, user_id=user.id, name="home", url="http://ha/mcp", headers={}
    ).execute()
    off = next(t for t in server.tools if t.name == "turn_off")
    await SetMcpToolEnabled(
        maker, user_id=user.id, server_id=server.id, tool_id=off.id, enabled=False
    ).execute()

    async def discover_v2(url, headers):  # type: ignore[no-untyped-def]
        # turn_on stays, turn_off stays (disabled must persist), lock is new
        return [
            DiscoveredTool("turn_on", "d", {}),
            DiscoveredTool("turn_off", None, None),
            DiscoveredTool("lock", "new", {}),
        ]

    monkeypatch.setattr(mcp_adapter, "discover", discover_v2)
    refreshed = await RefreshMcpServer(maker, user_id=user.id, server_id=server.id).execute()
    assert refreshed is not None
    by_name = {t.name: t for t in refreshed.tools}
    assert set(by_name) == {"turn_on", "turn_off", "lock"}
    assert by_name["turn_off"].enabled is False  # preserved
    assert by_name["lock"].enabled is True  # new default
