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


class DeepAgentRunner:
    """Run a DeepAgents graph and normalize its events for Chainlit."""

    def __init__(self, graph: EventStreamingGraph) -> None:
        """Store the compiled graph."""
        self._graph = graph

    async def stream(
        self,
        content: str,
        *,
        model: str,
        thread_id: str,
    ) -> AsyncIterator[RunnerEvent]:
        """Stream normalized text/tool events for one user message."""
        payload: dict[str, object] = {
            "messages": [{"role": "user", "content": content}],
            "model": model,
        }
        config = {"configurable": {"thread_id": thread_id}}
        async for event in self._graph.astream_events(payload, version="v2", config=config):
            normalized = self._normalize_event(event)
            if normalized is not None:
                yield normalized

    def _normalize_event(self, event: dict[str, object]) -> RunnerEvent | None:
        """Map LangGraph event dictionaries into Capybara runner events."""
        if event.get("event") != "on_chat_model_stream":
            return None

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


ToolLike = BaseTool | Callable[..., Any] | dict[str, Any]


def build_graph(settings: Settings, tools: Sequence[ToolLike] | None = None) -> EventStreamingGraph:
    """Build the DeepAgents graph for Capybara chat runs."""
    registry = ModelRegistry(settings)
    graph = create_deep_agent(
        model=registry.chat_model(settings.default_model),
        tools=list(tools or []),
        system_prompt=(
            "You are CapybaraAgent, a local-first assistant. Use available tools when "
            "they help answer the user's request. Prefer clear, concise answers."
        ),
    )
    return cast(EventStreamingGraph, graph)
