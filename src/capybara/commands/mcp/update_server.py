"""Update an MCP server's mutable fields."""

from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.commands.base import BaseCommand
from capybara.commands.mcp.utils import owned_server
from capybara.db.models import McpServer
from capybara.repositories.mcp_repo import McpServerRepo


class UpdateMcpServer(BaseCommand[McpServer | None]):
    """Apply a partial update (name/url/headers/enabled) to a user-owned server."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        user_id: UUID,
        server_id: UUID,
        patch: BaseModel,
    ) -> None:
        """Store the sessionmaker, the target server, and the partial payload."""
        self._sessionmaker = sessionmaker
        self._user_id = user_id
        self._server_id = server_id
        self._patch = patch

    async def run(self) -> McpServer | None:
        """Update the server; return None if it is not owned."""
        async with self._sessionmaker() as session:
            server = await owned_server(session, self._user_id, self._server_id)
            if server is None:
                return None
            fields = self._patch.model_dump(exclude_unset=True, exclude_none=True)
            if fields:
                server = await McpServerRepo(session).update(server, **fields)
                await session.commit()
                # The UPDATE flush expires updated_at (onupdate); reload before the
                # session closes so serialization does not trigger a sync lazy load.
                await session.refresh(server)
            return server
