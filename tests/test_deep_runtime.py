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
    runner = DeepAgentRunner(lambda tools, model, mode: FakeGraph())
    events = [
        event
        async for event in runner.stream("Hi", model="llama3.1", thread_id="t1", mode="fast")
    ]
    assert events == [RunnerEvent(kind="text", content="hello", name=None, payload=None)]


async def test_runner_builds_graph_per_turn_with_tools_and_mode() -> None:
    """Each turn rebuilds the graph from that turn's tools, model, AND mode."""
    sentinel_tool = object()
    calls: list[tuple[list[ToolLike], str, str]] = []

    class FakeProvider:
        async def tools(self) -> Sequence[ToolLike]:
            return [sentinel_tool]  # type: ignore[list-item]

    def factory(tools: Sequence[ToolLike], model: str, mode: str) -> FakeGraph:
        calls.append((list(tools), model, mode))
        return FakeGraph()

    runner = DeepAgentRunner(factory, tool_provider=FakeProvider())
    events = [
        event
        async for event in runner.stream("Hi", model="llama3.1", thread_id="t1", mode="fast")
    ]

    assert calls == [([sentinel_tool], "llama3.1", "fast")]
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
    runner = DeepAgentRunner(lambda tools, model, mode: FakeToolGraph())
    events = [event async for event in runner.stream("hi", model="m", thread_id="t1", mode="fast")]
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

    def factory(tools: Sequence[ToolLike], model: str, mode: str) -> FakeGraph:
        calls.append(list(tools))
        return FakeGraph()

    runner = DeepAgentRunner(factory)
    events = [event async for event in runner.stream("Hi", model="m", thread_id="t1", mode="fast")]

    assert calls == [[]]
    assert events == [RunnerEvent(kind="text", content="hello", name=None, payload=None)]


async def test_build_fast_graph_wires_react_agent(
    settings, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """build_fast_graph hands the model, tools, and checkpointer to create_react_agent."""
    from capybara.agent import deep_runtime
    from capybara.agent.model_registry import ModelRegistry

    captured: dict[str, object] = {}

    def fake_create_react_agent(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return FakeGraph()

    monkeypatch.setattr(deep_runtime, "create_react_agent", fake_create_react_agent)
    sentinel_tool = object()
    sentinel_ckpt = object()

    deep_runtime.build_fast_graph(
        ModelRegistry(settings),
        [sentinel_tool],  # type: ignore[list-item]
        model="qwen2.5:latest",
        checkpointer=sentinel_ckpt,  # type: ignore[arg-type]
    )

    assert captured["model"].model == "qwen2.5:latest"  # type: ignore[union-attr]
    assert captured["tools"] == [sentinel_tool]
    assert captured["checkpointer"] is sentinel_ckpt


async def test_build_graph_wires_model_tools_and_checkpointer(settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """build_graph hands the selected chat model, tools, and checkpointer to DeepAgents."""
    from capybara.agent import deep_runtime
    from capybara.agent.model_registry import ModelRegistry

    captured: dict[str, object] = {}

    def fake_create_deep_agent(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return FakeGraph()

    monkeypatch.setattr(deep_runtime, "create_deep_agent", fake_create_deep_agent)
    sentinel_tool = object()
    sentinel_checkpointer = object()

    deep_runtime.build_graph(
        ModelRegistry(settings),
        [sentinel_tool],  # type: ignore[list-item]
        model="llama3.1:8b",
        checkpointer=sentinel_checkpointer,  # type: ignore[arg-type]
    )

    assert captured["model"].model == "llama3.1:8b"  # type: ignore[union-attr]
    assert captured["tools"] == [sentinel_tool]
    assert captured["checkpointer"] is sentinel_checkpointer
    assert captured["system_prompt"] == deep_runtime.SYSTEM_PROMPT
