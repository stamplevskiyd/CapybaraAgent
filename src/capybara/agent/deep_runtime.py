"""DeepAgents runner facade used by Chainlit callbacks."""

from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

from deepagents import create_deep_agent
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.prebuilt import create_react_agent

from capybara.agent.model_registry import ModelRegistry

#: The kinds of normalized events the runner emits.
RunnerEventKind = Literal["text", "tool_start", "tool_end"]

#: System prompt for every Capybara chat run.
SYSTEM_PROMPT = (
    "You are CapybaraAgent, a local-first assistant. Use available tools when "
    "they help answer the user's request. Prefer clear, concise answers."
)

#: Recursion cap for the Fast (react) loop — keeps a confused weak model from spinning.
FAST_RECURSION_LIMIT = 6

#: System prompt for the Fast react loop.
FAST_SYSTEM_PROMPT = (
    "You are CapybaraAgent, a local-first assistant. Answer directly and concisely. "
    "Use a tool only when it is clearly needed."
)


@dataclass(frozen=True)
class RunnerEvent:
    """Normalized event emitted by the agent runtime."""

    kind: RunnerEventKind
    content: str | None = None
    name: str | None = None
    payload: dict[str, Any] | None = None


class EventStreamingGraph(Protocol):
    """Protocol for DeepAgents/LangGraph objects that stream events."""

    def astream_events(
        self,
        graph_input: dict[str, object],
        **kwargs: object,
    ) -> AsyncIterator[dict[str, object]]:
        """Stream LangGraph events."""
        ...


ToolLike = BaseTool | Callable[..., Any]

#: Build a graph for one turn from that turn's tools, selected model, and mode.
GraphFactory = Callable[[Sequence["ToolLike"], str, str], EventStreamingGraph]


@dataclass(frozen=True)
class McpServerSpec:
    """One enabled MCP server's connection details and the tool names it may expose.

    ``prefix`` (the server slug) namespaces every tool as ``{prefix}_{name}`` so names never
    collide across servers, matching how the tools are exposed to the model. Defined here (a
    services-free module) so both the MCP service and the tool builder can share it without
    an import cycle.
    """

    prefix: str
    url: str
    headers: dict[str, str]
    enabled_tools: frozenset[str]


class ToolProvider(Protocol):
    """Supplies the tools a turn's agent graph should expose."""

    async def tools(self) -> Sequence[ToolLike]:
        """Return the tools available to the agent for the current turn."""
        ...


class DeepAgentRunner:
    """Run a DeepAgents graph and normalize its events for Chainlit.

    The graph is rebuilt each turn by *graph_factory* from the selected model and the
    *tool_provider*'s tools — a graph built once at startup could not know the caller, and
    memory/MCP tools are per-user.
    """

    def __init__(
        self,
        graph_factory: GraphFactory,
        tool_provider: ToolProvider | None = None,
    ) -> None:
        """Store the per-turn graph factory and the optional tool provider."""
        self._graph_factory = graph_factory
        self._tool_provider = tool_provider

    async def stream(
        self,
        content: str,
        *,
        model: str,
        thread_id: str,
        mode: str,
    ) -> AsyncIterator[RunnerEvent]:
        """Stream normalized text/tool events for one user message."""
        tools: Sequence[ToolLike] = []
        if self._tool_provider is not None:
            tools = await self._tool_provider.tools()
        graph = self._graph_factory(tools, model, mode)
        payload: dict[str, object] = {"messages": [{"role": "user", "content": content}]}
        config: dict[str, object] = {"configurable": {"thread_id": thread_id}}
        if mode == "fast":
            config["recursion_limit"] = FAST_RECURSION_LIMIT
        async for event in graph.astream_events(payload, version="v2", config=config):
            normalized = self._normalize_event(event)
            if normalized is not None:
                yield normalized

    def _normalize_event(self, event: dict[str, object]) -> RunnerEvent | None:
        """Map LangGraph event dictionaries into Capybara runner events."""
        kind = event.get("event")
        if kind == "on_chat_model_stream":
            return self._normalize_text(event)
        if kind in ("on_tool_start", "on_tool_end"):
            return self._normalize_tool(event, kind)
        return None

    def _normalize_text(self, event: dict[str, object]) -> RunnerEvent | None:
        """Extract a streamed text token from a chat-model-stream event."""
        data = event.get("data")
        if not isinstance(data, dict):
            return None

        chunk = data.get("chunk")
        if isinstance(chunk, str):
            return RunnerEvent(kind="text", content=chunk)

        content = getattr(chunk, "content", None)
        if isinstance(content, str) and content:
            return RunnerEvent(kind="text", content=content)

        return None

    def _normalize_tool(self, event: dict[str, object], graph_event: str) -> RunnerEvent:
        """Turn a tool start/end event into a runner event keyed by its run id.

        The run id correlates the start and end so the UI can open a step on start and
        finalize the same step on end; the input (start) or output (end) rides in the
        payload.
        """
        opening = graph_event == "on_tool_start"
        name = event.get("name")
        data = event.get("data")
        field = "input" if opening else "output"
        payload: dict[str, Any] = {"run_id": event.get("run_id")}
        if isinstance(data, dict):
            payload[field] = data.get(field)
        return RunnerEvent(
            kind="tool_start" if opening else "tool_end",
            name=str(name) if name is not None else None,
            payload=payload,
        )


def build_graph(
    registry: ModelRegistry,
    tools: Sequence[ToolLike] | None = None,
    *,
    model: str,
    checkpointer: BaseCheckpointSaver[str] | None = None,
) -> EventStreamingGraph:
    """Build the DeepAgents graph for one Capybara chat turn.

    *model* selects the chat model for the turn. *checkpointer* carries conversation state
    across turns: the graph itself is rebuilt per turn (tools and model change), so any
    memory of earlier messages lives in the shared checkpointer, keyed by the ``thread_id``
    the runner passes in its config.
    """
    graph = create_deep_agent(
        model=registry.chat_model(model),
        tools=list(tools or []),
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )
    return cast(EventStreamingGraph, graph)


def build_fast_graph(
    registry: ModelRegistry,
    tools: Sequence[ToolLike] | None = None,
    *,
    model: str,
    checkpointer: BaseCheckpointSaver[str] | None = None,
) -> EventStreamingGraph:
    """Build the simple react-loop graph for Fast mode.

    A ``create_react_agent`` graph: one model+tools loop, no planning or subagents, for
    weak local models. Same LangGraph event stream and checkpointer contract as the Smart
    graph, so the runner and UI need no changes.
    """
    graph = create_react_agent(
        model=registry.chat_model(model),
        tools=list(tools or []),
        prompt=FAST_SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )
    return cast(EventStreamingGraph, graph)
