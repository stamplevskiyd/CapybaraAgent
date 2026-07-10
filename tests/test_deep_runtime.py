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
    runner = DeepAgentRunner(lambda tools, model: FakeGraph())
    events = [event async for event in runner.stream("Hi", model="llama3.1", thread_id="t1")]
    assert events == [RunnerEvent(kind="text", content="hello", name=None, payload=None)]


async def test_runner_builds_graph_per_turn_with_provided_tools() -> None:
    """With a factory + provider, each turn rebuilds the graph from that turn's tools/model."""
    sentinel_tool = object()
    calls: list[tuple[list[ToolLike], str]] = []

    class FakeProvider:
        async def tools(self) -> Sequence[ToolLike]:
            return [sentinel_tool]  # type: ignore[list-item]

    def factory(tools: Sequence[ToolLike], model: str) -> FakeGraph:
        calls.append((list(tools), model))
        return FakeGraph()

    runner = DeepAgentRunner(factory, tool_provider=FakeProvider())
    events = [event async for event in runner.stream("Hi", model="llama3.1", thread_id="t1")]

    assert calls == [([sentinel_tool], "llama3.1")]
    assert events == [RunnerEvent(kind="text", content="hello", name=None, payload=None)]


class FakeToolGraph:
    """Fake graph that emits a tool-call lifecycle around a text token."""

    async def astream_events(
        self,
        _input: dict[str, object],
        **_kwargs: object,
    ) -> AsyncIterator[dict[str, object]]:
        """Yield tool start/end events (with a text token in between)."""
        yield {
            "event": "on_tool_start",
            "name": "recall",
            "run_id": "r1",
            "data": {"input": {"query": "x"}},
        }
        yield {"event": "on_chat_model_stream", "data": {"chunk": "ok"}}
        yield {
            "event": "on_tool_end",
            "name": "recall",
            "run_id": "r1",
            "data": {"output": "facts"},
        }


async def test_runner_normalizes_tool_start_and_end_events() -> None:
    """Tool lifecycle events become tool_start/tool_end runner events keyed by run_id."""
    runner = DeepAgentRunner(lambda tools, model: FakeToolGraph())
    events = [event async for event in runner.stream("hi", model="m", thread_id="t1")]
    assert events == [
        RunnerEvent(
            kind="tool_start", name="recall", payload={"run_id": "r1", "input": {"query": "x"}}
        ),
        RunnerEvent(kind="text", content="ok"),
        RunnerEvent(kind="tool_end", name="recall", payload={"run_id": "r1", "output": "facts"}),
    ]


async def test_runner_factory_without_provider_builds_toolless_graph() -> None:
    """A factory with no provider still builds a graph, just with an empty tool list."""
    calls: list[list[ToolLike]] = []

    def factory(tools: Sequence[ToolLike], model: str) -> FakeGraph:
        calls.append(list(tools))
        return FakeGraph()

    runner = DeepAgentRunner(factory)
    events = [event async for event in runner.stream("Hi", model="m", thread_id="t1")]

    assert calls == [[]]
    assert events == [RunnerEvent(kind="text", content="hello", name=None, payload=None)]
