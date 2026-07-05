"""Recall tool: bridges the chat agent's tool seam to MemoryService."""

from uuid import UUID

from pydantic_ai import Tool

from capybara.db.models import Fact
from capybara.services.memory_service import MemoryService


def format_facts(facts: list[Fact]) -> str:
    """Render recalled facts as a short bullet list for the model, or a not-found note."""
    if not facts:
        return "No relevant facts found."
    return "\n".join(f"- [{fact.category}] {fact.content}" for fact in facts)


def make_recall_tool(memory_service: MemoryService, user_id: UUID) -> Tool[None]:
    """Build a pydantic-ai recall tool closed over the service and user.

    The tool takes no pydantic-ai ``deps`` — the service and user are captured in the
    closure, so it composes into the generic ``stream_reply(tools=…)`` list unchanged.
    """

    async def recall(query: str) -> str:
        """Search the user's long-term memory for relevant facts."""
        return format_facts(await memory_service.recall(user_id, query))

    return Tool(recall)
