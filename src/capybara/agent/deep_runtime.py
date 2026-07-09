"""DeepAgents runner facade used by Chainlit callbacks."""

from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast

from deepagents import create_deep_agent
from langchain_core.tools import BaseTool

from capybara.agent.model_registry import ModelRegistry
from capybara.config import Settings


@dataclass(frozen=True)
class RunnerEvent:
    """Normalized event emitted by the agent runtime."""

    kind: str
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


ToolLike = BaseTool | Callable[..., Any] | dict[str, Any]

#: Build a graph for one turn from that turn's tools and selected model.
GraphFactory = Callable[[Sequence["ToolLike"], str], EventStreamingGraph]


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

    async def tools_for(self, thread_id: str) -> Sequence[ToolLike]:
        """Return the tools available to the agent for *thread_id*."""
        ...


class DeepAgentRunner:
    """Run a DeepAgents graph and normalize its events for Chainlit.

    Either a fixed *graph* is streamed on every turn, or a *graph_factory* rebuilds the
    graph per turn from the selected model and the *tool_provider*'s tools — the latter is
    what lets per-user memory/MCP tools reach the model, since a startup graph cannot know
    the caller.
    """

    def __init__(
        self,
        graph: EventStreamingGraph | None = None,
        *,
        graph_factory: GraphFactory | None = None,
        tool_provider: ToolProvider | None = None,
    ) -> None:
        """Store either a fixed graph or a per-turn factory (with optional tool provider)."""
        if graph is None and graph_factory is None:
            raise ValueError("DeepAgentRunner requires either a graph or a graph_factory")
        self._graph = graph
        self._graph_factory = graph_factory
        self._tool_provider = tool_provider

    async def _graph_for_turn(self, model: str, thread_id: str) -> EventStreamingGraph:
        """Return the fixed graph, or build a fresh one from this turn's tools and model."""
        if self._graph_factory is None:
            assert self._graph is not None  # guaranteed by __init__
            return self._graph
        tools: Sequence[ToolLike] = []
        if self._tool_provider is not None:
            tools = await self._tool_provider.tools_for(thread_id)
        return self._graph_factory(tools, model)

    async def stream(
        self,
        content: str,
        *,
        model: str,
        thread_id: str,
    ) -> AsyncIterator[RunnerEvent]:
        """Stream normalized text/tool events for one user message."""
        graph = await self._graph_for_turn(model, thread_id)
        payload: dict[str, object] = {
            "messages": [{"role": "user", "content": content}],
            "model": model,
        }
        config = {"configurable": {"thread_id": thread_id}}
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
    settings: Settings,
    tools: Sequence[ToolLike] | None = None,
    *,
    model: str | None = None,
) -> EventStreamingGraph:
    """Build the DeepAgents graph for Capybara chat runs.

    *model* selects the chat model for the turn; it falls back to the configured default so
    startup builds and toolless tests need not pass one.
    """
    registry = ModelRegistry(settings)
    graph = create_deep_agent(
        model=registry.chat_model(model or settings.default_model),
        tools=list(tools or []),
        system_prompt=(
            "You are CapybaraAgent, a local-first assistant. Use available tools when "
            "they help answer the user's request. Prefer clear, concise answers."
        ),
    )
    return cast(EventStreamingGraph, graph)
