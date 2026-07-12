"""Tests for LangChain tool factories used by the DeepAgents runtime."""

from uuid import UUID, uuid4

from langchain_core.tools import BaseTool

from capybara.agent.deep_tools import (
    McpServerSpec,
    UserToolProvider,
    build_mcp_tools,
    make_recall_tool,
)
from capybara.db.models import Fact


class FakeTool:
    """Minimal stand-in for a LangChain tool; only its name is inspected."""

    def __init__(self, name: str) -> None:
        """Store the tool name."""
        self.name = name


class FakeMcpSpecService:
    """MCP service fake that records spec lookups and returns canned specs."""

    def __init__(self, specs: list[McpServerSpec]) -> None:
        """Store the specs to return and prepare a call log."""
        self._specs = specs
        self.calls: list[object] = []

    async def enabled_tool_specs(self, user_id: object) -> list[McpServerSpec]:
        """Record the call and return the canned specs."""
        self.calls.append(user_id)
        return self._specs


class FakeRecallService:
    """Recall fake that records calls and returns canned facts."""

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
    tool = make_recall_tool(FakeRecallService([]).recall, uuid4())

    assert isinstance(tool, BaseTool)
    assert tool.name == "recall"
    assert tool.description
    assert "query" in tool.args


async def test_recall_tool_formats_facts_and_scopes_to_user() -> None:
    """Invoking the tool recalls for the bound user and wraps facts as untrusted data."""
    user_id = uuid4()
    service = FakeRecallService([Fact(category="personal", content="Likes hiking")])
    tool = make_recall_tool(service.recall, user_id)

    result = await tool.ainvoke({"query": "hobbies"})

    assert service.calls == [(user_id, "hobbies")]
    assert "Likes hiking" in result
    assert "user_memory" in result


async def test_recall_tool_reports_no_facts() -> None:
    """An empty recall yields the plain not-found note, nothing to mark as untrusted."""
    tool = make_recall_tool(FakeRecallService([]).recall, uuid4())

    assert await tool.ainvoke({"query": "anything"}) == "No relevant facts found."


async def test_provider_yields_recall_tool_for_current_user() -> None:
    """With a resolvable user and a recall fn, the provider hands over that user's recall tool."""
    user_id = uuid4()
    provider = UserToolProvider(FakeRecallService([]).recall, None, get_user_id=lambda: user_id)

    tools = await provider.tools()

    assert [tool.name for tool in tools] == ["recall"]


async def test_provider_yields_nothing_without_a_user() -> None:
    """No authenticated user this turn → no per-user tools, and no MCP service is queried."""
    service = FakeMcpSpecService([McpServerSpec("home", "http://h", {}, frozenset({"a"}))])
    provider = UserToolProvider(
        FakeRecallService([]).recall, service.enabled_tool_specs, get_user_id=lambda: None
    )

    assert await provider.tools() == []
    assert service.calls == []


async def test_provider_skips_recall_without_a_recall_fn() -> None:
    """No recall callable configured → no recall tool, even with a user."""
    provider = UserToolProvider(None, None, get_user_id=uuid4)

    assert await provider.tools() == []


async def test_build_mcp_tools_keeps_only_enabled_prefixed_tools() -> None:
    """A server's tools are namespaced by prefix and filtered to the enabled set."""
    spec = McpServerSpec(
        prefix="home", url="http://ha/mcp", headers={}, enabled_tools=frozenset({"turn_on"})
    )

    async def loader(s: McpServerSpec) -> list[object]:
        assert s is spec
        return [FakeTool("home_turn_on"), FakeTool("home_turn_off")]

    tools = await build_mcp_tools([spec], loader=loader)

    assert [tool.name for tool in tools] == ["home_turn_on"]


async def test_build_mcp_tools_skips_unreachable_server() -> None:
    """A server whose loader raises is skipped (fail-open); reachable servers still load."""
    good = McpServerSpec("good", "http://g/mcp", {}, frozenset({"a"}))
    bad = McpServerSpec("bad", "http://b/mcp", {}, frozenset({"a"}))

    async def loader(s: McpServerSpec) -> list[object]:
        if s.prefix == "bad":
            raise RuntimeError("connection refused")
        return [FakeTool("good_a")]

    tools = await build_mcp_tools([bad, good], loader=loader)

    assert [tool.name for tool in tools] == ["good_a"]


async def test_build_mcp_tools_skips_servers_with_no_enabled_tools() -> None:
    """A server with nothing enabled is never contacted."""
    spec = McpServerSpec("home", "http://ha/mcp", {}, frozenset())
    contacted = False

    async def loader(s: McpServerSpec) -> list[object]:
        nonlocal contacted
        contacted = True
        return []

    tools = await build_mcp_tools([spec], loader=loader)

    assert tools == []
    assert contacted is False


async def test_provider_looks_up_mcp_specs_for_current_user() -> None:
    """The provider resolves the user and asks for that user's MCP specs."""
    user_id = uuid4()
    service = FakeMcpSpecService([])  # empty specs → no server contact
    provider = UserToolProvider(None, service.enabled_tool_specs, get_user_id=lambda: user_id)

    assert await provider.tools() == []
    assert service.calls == [user_id]


async def test_provider_without_an_mcp_specs_fn_yields_no_mcp_tools() -> None:
    """No specs callable configured → no MCP tools."""
    provider = UserToolProvider(None, None, get_user_id=uuid4)

    assert await provider.tools() == []


async def test_provider_concatenates_memory_then_mcp_tools(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The provider returns memory tools first, then MCP tools, for the resolved user."""
    from capybara.agent import deep_tools

    async def fake_build_mcp_tools(specs: object, **_kwargs: object) -> list[FakeTool]:
        return [FakeTool("home_turn_on")]

    monkeypatch.setattr(deep_tools, "build_mcp_tools", fake_build_mcp_tools)
    service = FakeMcpSpecService([McpServerSpec("home", "http://h", {}, frozenset({"a"}))])
    provider = UserToolProvider(
        FakeRecallService([]).recall, service.enabled_tool_specs, get_user_id=uuid4
    )

    tools = await provider.tools()

    assert [tool.name for tool in tools] == ["recall", "home_turn_on"]
