"""API tests for the /mcp router, with the MCP adapter mocked."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from capybara.agent import mcp as mcp_adapter
from capybara.agent.mcp import DiscoveredTool, McpUnreachableError
from capybara.api.dependencies import (
    get_agent,
    get_current_user,
    get_session,
    get_sessionmaker,
    get_settings_dep,
)
from capybara.config import Settings
from capybara.db.engine import create_sessionmaker
from capybara.db.models import User
from capybara.main import app
from support import FakeAgent

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def mcp_client(engine: AsyncEngine, settings: Settings, make_user):  # type: ignore[no-untyped-def]
    """Authenticated AsyncClient with the MCP router wired to the test database."""
    maker = create_sessionmaker(engine)
    async with maker() as setup:
        user = await make_user(setup, username="mcp_user", display_name="MCP User")
        await setup.commit()
        user_id = user.id

    async def _override_session():  # type: ignore[no-untyped-def]
        async with maker() as sess:
            try:
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                raise

    async def _override_user():  # type: ignore[no-untyped-def]
        async with maker() as sess:
            fetched = await sess.get(User, user_id)
            assert fetched is not None
            yield fetched

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_sessionmaker] = lambda: maker
    app.dependency_overrides[get_settings_dep] = lambda: settings
    app.dependency_overrides[get_agent] = lambda: FakeAgent(settings, output_text="ok")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_attach_list_and_toggle_tool(mcp_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Attach a server, list it with tools, then disable one tool."""

    async def fake_discover(url, headers):  # type: ignore[no-untyped-def]
        return [DiscoveredTool("turn_on", "d", {}), DiscoveredTool("turn_off", None, None)]

    monkeypatch.setattr(mcp_adapter, "discover", fake_discover)

    resp = await mcp_client.post(
        "/mcp/servers",
        json={"name": "home", "url": "http://ha/mcp", "headers": {"X-Api-Key": "k"}},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "home"
    assert {t["name"] for t in body["tools"]} == {"turn_on", "turn_off"}
    assert "headers" not in body  # auth headers are write-only; must not appear in attach response
    server_id = body["id"]
    tool_id = next(t["id"] for t in body["tools"] if t["name"] == "turn_off")

    listed = await mcp_client.get("/mcp/servers")
    assert listed.status_code == 200
    assert [s["name"] for s in listed.json()] == ["home"]
    for server in listed.json():
        assert "headers" not in server  # auth headers must not appear in list responses either

    toggled = await mcp_client.patch(
        f"/mcp/servers/{server_id}/tools/{tool_id}", json={"enabled": False}
    )
    assert toggled.status_code == 200
    assert toggled.json()["enabled"] is False


async def test_attach_unreachable_returns_502(mcp_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A server that can't be reached returns 502 with an actionable message."""

    async def boom(url, headers):  # type: ignore[no-untyped-def]
        raise McpUnreachableError("connection refused")

    monkeypatch.setattr(mcp_adapter, "discover", boom)
    resp = await mcp_client.post(
        "/mcp/servers", json={"name": "home", "url": "http://ha/mcp", "headers": {}}
    )
    assert resp.status_code == 502
    assert "refused" in resp.json()["detail"]


async def test_delete_server(mcp_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Deleting a server returns 204 and removes it from the list."""

    async def fake_discover(url, headers):  # type: ignore[no-untyped-def]
        return [DiscoveredTool("turn_on", "d", {})]

    monkeypatch.setattr(mcp_adapter, "discover", fake_discover)
    created = await mcp_client.post(
        "/mcp/servers", json={"name": "home", "url": "http://ha/mcp", "headers": {}}
    )
    server_id = created.json()["id"]
    deleted = await mcp_client.delete(f"/mcp/servers/{server_id}")
    assert deleted.status_code == 204
    assert (await mcp_client.get("/mcp/servers")).json() == []
