"""LangChain tool factories that expose Capybara services to the DeepAgents runtime.

Ports the pydantic-ai tool seam (``capybara.services.memory_tools``) to LangChain
``BaseTool`` instances the DeepAgents graph can register. The formatting/untrusted-memory
boundary is reused unchanged so recalled facts keep their prompt-injection guard.
"""

from collections.abc import Callable, Sequence
from typing import Protocol
from uuid import UUID

from langchain_core.tools import BaseTool, StructuredTool

from capybara.agent.deep_runtime import ToolLike
from capybara.db.models import Fact
from capybara.services.memory_tools import format_facts

#: Resolve the user whose tools this turn should expose, or None when unauthenticated.
UserIdGetter = Callable[[], UUID | None]


class SupportsRecall(Protocol):
    """Subset of ``MemoryService`` needed to build the recall tool."""

    async def recall(self, user_id: UUID, query: str) -> list[Fact]:
        """Return facts semantically nearest to *query* for *user_id*."""
        ...


def make_recall_tool(memory_service: SupportsRecall, user_id: UUID) -> BaseTool:
    """Build a LangChain recall tool closed over the service and user.

    The service and user are captured in the closure so the tool takes only a ``query``
    argument, letting it drop into the DeepAgents graph's tool list unchanged. Results pass
    through ``format_facts`` so recalled user text stays wrapped in its untrusted-memory
    boundary.
    """

    async def recall(query: str) -> str:
        """Search the user's long-term memory for relevant facts."""
        return format_facts(await memory_service.recall(user_id, query))

    return StructuredTool.from_function(
        coroutine=recall,
        name="recall",
        description="Search the user's long-term memory for relevant facts.",
    )


class MemoryToolProvider:
    """Hand the DeepAgents runner the current user's memory tools, rebuilt each turn.

    Memory is per-user, so the tool must bind to whoever the turn belongs to. The user id
    is resolved lazily via *get_user_id* (the Chainlit session) rather than captured once,
    and an unresolved user yields no tools — a turn never reaches another user's memory.
    """

    def __init__(self, memory_service: SupportsRecall | None, *, get_user_id: UserIdGetter) -> None:
        """Store the memory service and the per-turn user resolver."""
        self._memory_service = memory_service
        self._get_user_id = get_user_id

    async def tools_for(self, thread_id: str) -> Sequence[ToolLike]:
        """Return the recall tool bound to this turn's user, or nothing if unresolved."""
        user_id = self._get_user_id()
        if user_id is None or self._memory_service is None:
            return []
        return [make_recall_tool(self._memory_service, user_id)]
