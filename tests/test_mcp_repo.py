"""Tests for the MCP repositories against a real Postgres session."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from capybara.db.models import McpServer, McpTool
from capybara.filters import FieldEquals
from capybara.repositories.mcp_repo import McpServerRepo

pytestmark = pytest.mark.asyncio


async def test_server_and_tools_roundtrip(session: AsyncSession, make_user) -> None:  # type: ignore[no-untyped-def]
    """Create a server with tools; the relationship returns them; user filter scopes."""
    user = await make_user(session)
    servers = McpServerRepo(session)

    server = await servers.create(
        user_id=user.id,
        name="home",
        url="http://ha/mcp",
        headers={"Authorization": "Bearer x"},
        tools=[
            McpTool(name="turn_on", description="d", input_schema={}),
            McpTool(name="turn_off", description=None, input_schema=None),
        ],
    )

    listed = await servers.get_list(FieldEquals(McpServer.user_id, user.id))
    assert [s.name for s in listed] == ["home"]
    assert listed[0].headers == {"Authorization": "Bearer x"}

    assert {t.name for t in server.tools} == {"turn_on", "turn_off"}
    assert all(t.enabled for t in server.tools)  # default enabled
