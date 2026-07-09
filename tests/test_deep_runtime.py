"""Tests for the DeepAgents runner facade."""

from collections.abc import AsyncIterator, Sequence

from capybara.agent.deep_runtime import DeepAgentRunner, RunnerEvent, ToolLike


class FakeGraph:
    """Small fake graph that yields one text event."""

    async def astream_events(
        self,
        _input: dict[str, object],
        **_kwargs: object,
    ) -> AsyncIterator[dict[str, object]]:
        """Yield a single LangGraph-style model stream event."""
        yield {"event": "on_chat_model_stream", "data": {"chunk": "hello"}}


async def test_runner_streams_text_events() -> None:
    """The runner normalizes graph stream events into text events."""
    runner = DeepAgentRunner(graph=FakeGraph())
    events = [event async for event in runner.stream("Hi", model="llama3.1", thread_id="t1")]
    assert events == [RunnerEvent(kind="text", content="hello", name=None, payload=None)]


async def test_runner_builds_graph_per_turn_with_provided_tools() -> None:
    """With a factory + provider, each turn rebuilds the graph from that turn's tools/model."""
    sentinel_tool = object()
    calls: list[tuple[list[ToolLike], str]] = []

    class FakeProvider:
        async def tools_for(self, thread_id: str) -> Sequence[ToolLike]:
            assert thread_id == "t1"
            return [sentinel_tool]  # type: ignore[list-item]

    def factory(tools: Sequence[ToolLike], model: str) -> FakeGraph:
        calls.append((list(tools), model))
        return FakeGraph()

    runner = DeepAgentRunner(graph_factory=factory, tool_provider=FakeProvider())
    events = [event async for event in runner.stream("Hi", model="llama3.1", thread_id="t1")]

    assert calls == [([sentinel_tool], "llama3.1")]
    assert events == [RunnerEvent(kind="text", content="hello", name=None, payload=None)]


async def test_runner_factory_without_provider_builds_toolless_graph() -> None:
    """A factory with no provider still builds a graph, just with an empty tool list."""
    calls: list[list[ToolLike]] = []

    def factory(tools: Sequence[ToolLike], model: str) -> FakeGraph:
        calls.append(list(tools))
        return FakeGraph()

    runner = DeepAgentRunner(graph_factory=factory)
    events = [event async for event in runner.stream("Hi", model="m", thread_id="t1")]

    assert calls == [[]]
    assert events == [RunnerEvent(kind="text", content="hello", name=None, payload=None)]
