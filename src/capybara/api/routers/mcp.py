"""Router for MCP server management and per-tool curation."""

from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from capybara.agent.mcp import McpProtocolError, McpUnreachableError
from capybara.api.dependencies import CurrentUser, Sessionmaker
from capybara.api.schemas import (
    McpServerCreate,
    McpServerOut,
    McpServerUpdate,
    McpToolOut,
    McpToolUpdate,
)
from capybara.commands.mcp.attach import AttachMcpServer
from capybara.commands.mcp.delete_server import DeleteMcpServer
from capybara.commands.mcp.get_server import GetMcpServer
from capybara.commands.mcp.list_servers import ListMcpServers
from capybara.commands.mcp.refresh import RefreshMcpServer
from capybara.commands.mcp.set_tool_enabled import SetMcpToolEnabled
from capybara.commands.mcp.update_server import UpdateMcpServer

router = APIRouter(prefix="/mcp", tags=["mcp"])


def _raise_for_mcp_error(exc: McpUnreachableError | McpProtocolError) -> NoReturn:
    """Translate an MCP connection failure into an actionable HTTP error.

    Unreachable → 502 (upstream outage); protocol/handshake failure → 400 (bad config).
    """
    if isinstance(exc, McpUnreachableError):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/servers", response_model=list[McpServerOut])
async def list_servers(user: CurrentUser, sessionmaker: Sessionmaker) -> list[McpServerOut]:
    """Return the current user's MCP servers with their tools."""
    servers = await ListMcpServers(sessionmaker, user_id=user.id).execute()
    return [McpServerOut.model_validate(s) for s in servers]


@router.post("/servers", status_code=status.HTTP_201_CREATED, response_model=McpServerOut)
async def attach_server(
    payload: McpServerCreate,
    user: CurrentUser,
    sessionmaker: Sessionmaker,
) -> McpServerOut:
    """Attach an MCP server: validate the connection and persist it with its tools."""
    command = AttachMcpServer(
        sessionmaker,
        user_id=user.id,
        name=payload.name,
        url=payload.url,
        headers=payload.headers,
    )
    try:
        server = await command.execute()
    except (McpUnreachableError, McpProtocolError) as exc:
        _raise_for_mcp_error(exc)
    return McpServerOut.model_validate(server)


@router.get("/servers/{server_id}", response_model=McpServerOut)
async def get_server(
    server_id: UUID,
    user: CurrentUser,
    sessionmaker: Sessionmaker,
) -> McpServerOut:
    """Return a single MCP server with its tools (404 if not owned)."""
    server = await GetMcpServer(sessionmaker, user_id=user.id, server_id=server_id).execute()
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found")
    return McpServerOut.model_validate(server)


@router.patch("/servers/{server_id}", response_model=McpServerOut)
async def update_server(
    server_id: UUID,
    payload: McpServerUpdate,
    user: CurrentUser,
    sessionmaker: Sessionmaker,
) -> McpServerOut:
    """Update a server's name/url/headers/enabled (404 if not owned)."""
    server = await UpdateMcpServer(
        sessionmaker, user_id=user.id, server_id=server_id, patch=payload
    ).execute()
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found")
    return McpServerOut.model_validate(server)


@router.delete("/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server(
    server_id: UUID,
    user: CurrentUser,
    sessionmaker: Sessionmaker,
) -> None:
    """Delete an MCP server and its tools (404 if not owned)."""
    if not await DeleteMcpServer(sessionmaker, user_id=user.id, server_id=server_id).execute():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found")


@router.post("/servers/{server_id}/refresh", response_model=McpServerOut)
async def refresh_server(
    server_id: UUID,
    user: CurrentUser,
    sessionmaker: Sessionmaker,
) -> McpServerOut:
    """Re-discover a server's tools, preserving enabled flags (404 if not owned)."""
    command = RefreshMcpServer(sessionmaker, user_id=user.id, server_id=server_id)
    try:
        server = await command.execute()
    except (McpUnreachableError, McpProtocolError) as exc:
        _raise_for_mcp_error(exc)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found")
    return McpServerOut.model_validate(server)


@router.patch("/servers/{server_id}/tools/{tool_id}", response_model=McpToolOut)
async def update_tool(
    server_id: UUID,
    tool_id: UUID,
    payload: McpToolUpdate,
    user: CurrentUser,
    sessionmaker: Sessionmaker,
) -> McpToolOut:
    """Toggle a tool's enabled flag (curation); 404 if the server/tool is not owned."""
    tool = await SetMcpToolEnabled(
        sessionmaker,
        user_id=user.id,
        server_id=server_id,
        tool_id=tool_id,
        enabled=payload.enabled,
    ).execute()
    if tool is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP tool not found")
    return McpToolOut.model_validate(tool)
