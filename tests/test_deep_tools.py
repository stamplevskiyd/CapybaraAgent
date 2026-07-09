"""Tests for LangChain tool factories used by the DeepAgents runtime."""

from uuid import UUID, uuid4

from langchain_core.tools import BaseTool

from capybara.agent.deep_tools import MemoryToolProvider, make_recall_tool
from capybara.db.models import Fact


class FakeRecallService:
    """Memory service fake that records recall calls and returns canned facts."""

    def __init__(self, facts: list[Fact]) -> None:
        """Store the facts to return and prepare a call log."""
        self._facts = facts
        self.calls: list[tuple[UUID, str]] = []

    async def recall(self, user_id: UUID, query: str) -> list[Fact]:
        """Record the call and return the canned facts."""
        self.calls.append((user_id, query))
        return self._facts


async def test_make_recall_tool_is_a_named_langchain_tool() -> None:
    """The factory returns a LangChain BaseTool the agent can register."""
    tool = make_recall_tool(FakeRecallService([]), uuid4())

    assert isinstance(tool, BaseTool)
    assert tool.name == "recall"
    assert tool.description
    assert "query" in tool.args


async def test_recall_tool_formats_facts_and_scopes_to_user() -> None:
    """Invoking the tool recalls for the bound user and wraps facts as untrusted data."""
    user_id = uuid4()
    service = FakeRecallService([Fact(category="personal", content="Likes hiking")])
    tool = make_recall_tool(service, user_id)

    result = await tool.ainvoke({"query": "hobbies"})

    assert service.calls == [(user_id, "hobbies")]
    assert "Likes hiking" in result
    assert "user_memory" in result


async def test_recall_tool_reports_no_facts() -> None:
    """An empty recall yields the plain not-found note, nothing to mark as untrusted."""
    tool = make_recall_tool(FakeRecallService([]), uuid4())

    assert await tool.ainvoke({"query": "anything"}) == "No relevant facts found."


async def test_provider_yields_recall_tool_for_current_user() -> None:
    """With a resolvable user, the provider hands the runner that user's recall tool."""
    user_id = uuid4()
    provider = MemoryToolProvider(FakeRecallService([]), get_user_id=lambda: user_id)

    tools = await provider.tools_for("thread-1")

    assert [tool.name for tool in tools] == ["recall"]


async def test_provider_yields_nothing_without_a_user() -> None:
    """No authenticated user this turn → no per-user tools (never leak another user's memory)."""
    provider = MemoryToolProvider(FakeRecallService([]), get_user_id=lambda: None)

    assert await provider.tools_for("thread-1") == []


async def test_provider_yields_nothing_without_a_memory_service() -> None:
    """No memory service configured → no recall tool, even with a user."""
    provider = MemoryToolProvider(None, get_user_id=uuid4)

    assert await provider.tools_for("thread-1") == []
