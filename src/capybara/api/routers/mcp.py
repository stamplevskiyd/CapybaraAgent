"""Router for MCP server management and per-tool curation."""

from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from capybara.agent.mcp import McpProtocolError, McpUnreachableError
from capybara.api.dependencies import get_current_user, get_mcp_service
from capybara.api.schemas import (
    McpServerCreate,
    McpServerOut,
    McpServerUpdate,
    McpToolOut,
    McpToolUpdate,
)
from capybara.db.models import McpServer, McpTool, User
from capybara.services.mcp_service import McpService

router = APIRouter(prefix="/mcp", tags=["mcp"])


def _server_out(server: McpServer, tools: list[McpTool]) -> McpServerOut:
    """Assemble a server + its tools into the response schema."""
    return McpServerOut(
        id=server.id,
        name=server.name,
        url=server.url,
        enabled=server.enabled,
        last_connected_at=server.last_connected_at,
        last_error=server.last_error,
        created_at=server.created_at,
        updated_at=server.updated_at,
        tools=[McpToolOut.model_validate(t) for t in tools],
    )


def _raise_for_mcp_error(exc: McpUnreachableError | McpProtocolError) -> NoReturn:
    """Translate an MCP connection failure into an actionable HTTP error.

    Unreachable → 502 (upstream outage); protocol/handshake failure → 400 (bad config).
    """
    if isinstance(exc, McpUnreachableError):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/servers", response_model=list[McpServerOut])
async def list_servers(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[McpService, Depends(get_mcp_service)],
) -> list[McpServerOut]:
    """Return the current user's MCP servers with their tools."""
    return [_server_out(s, tools) for s, tools in await service.list_servers(user.id)]


@router.post("/servers", status_code=status.HTTP_201_CREATED, response_model=McpServerOut)
async def attach_server(
    payload: McpServerCreate,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[McpService, Depends(get_mcp_service)],
) -> McpServerOut:
    """Attach an MCP server: validate the connection and persist it with its tools."""
    try:
        server, tools = await service.attach(user.id, payload.name, payload.url, payload.headers)
    except (McpUnreachableError, McpProtocolError) as exc:
        _raise_for_mcp_error(exc)
    return _server_out(server, tools)


@router.get("/servers/{server_id}", response_model=McpServerOut)
async def get_server(
    server_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[McpService, Depends(get_mcp_service)],
) -> McpServerOut:
    """Return a single MCP server with its tools (404 if not owned)."""
    loaded = await service.get_server(user.id, server_id)
    if loaded is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found")
    return _server_out(*loaded)


@router.patch("/servers/{server_id}", response_model=McpServerOut)
async def update_server(
    server_id: UUID,
    payload: McpServerUpdate,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[McpService, Depends(get_mcp_service)],
) -> McpServerOut:
    """Update a server's name/url/headers/enabled (404 if not owned)."""
    loaded = await service.update_server(
        user.id,
        server_id,
        name=payload.name,
        url=payload.url,
        headers=payload.headers,
        enabled=payload.enabled,
    )
    if loaded is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found")
    return _server_out(*loaded)


@router.delete("/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server(
    server_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[McpService, Depends(get_mcp_service)],
) -> None:
    """Delete an MCP server and its tools (404 if not owned)."""
    if not await service.delete_server(user.id, server_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found")


@router.post("/servers/{server_id}/refresh", response_model=McpServerOut)
async def refresh_server(
    server_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[McpService, Depends(get_mcp_service)],
) -> McpServerOut:
    """Re-discover a server's tools, preserving enabled flags (404 if not owned)."""
    try:
        loaded = await service.refresh(user.id, server_id)
    except (McpUnreachableError, McpProtocolError) as exc:
        _raise_for_mcp_error(exc)
    if loaded is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found")
    return _server_out(*loaded)


@router.patch("/servers/{server_id}/tools/{tool_id}", response_model=McpToolOut)
async def update_tool(
    server_id: UUID,
    tool_id: UUID,
    payload: McpToolUpdate,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[McpService, Depends(get_mcp_service)],
) -> McpToolOut:
    """Toggle a tool's enabled flag (curation); 404 if the server/tool is not owned."""
    tool = await service.set_tool_enabled(user.id, server_id, tool_id, enabled=payload.enabled)
    if tool is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP tool not found")
    return McpToolOut.model_validate(tool)
