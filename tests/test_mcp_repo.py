"""Tests for the MCP repositories against a real Postgres session."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from capybara.db.models import McpServer
from capybara.filters import FieldEquals
from capybara.repositories.mcp_repo import McpServerRepo, McpToolRepo

pytestmark = pytest.mark.asyncio


async def test_server_and_tools_roundtrip(session: AsyncSession, make_user) -> None:  # type: ignore[no-untyped-def]
    """Create a server with tools; list_for_server returns them; user filter scopes."""
    user = await make_user(session)
    servers = McpServerRepo(session)
    tools = McpToolRepo(session)

    server = await servers.create(
        user_id=user.id, name="home", url="http://ha/mcp", headers={"Authorization": "Bearer x"}
    )
    await tools.create(server_id=server.id, name="turn_on", description="d", input_schema={})
    await tools.create(server_id=server.id, name="turn_off", description=None, input_schema=None)

    listed = await servers.list(FieldEquals(McpServer.user_id, user.id))
    assert [s.name for s in listed] == ["home"]
    assert listed[0].headers == {"Authorization": "Bearer x"}

    server_tools = await tools.list_for_server(server.id)
    assert {t.name for t in server_tools} == {"turn_on", "turn_off"}
    assert all(t.enabled for t in server_tools)  # default enabled


async def test_list_for_server_empty_for_unknown(session: AsyncSession) -> None:
    """list_for_server returns [] for a server id with no tools."""
    assert await McpToolRepo(session).list_for_server(uuid4()) == []
