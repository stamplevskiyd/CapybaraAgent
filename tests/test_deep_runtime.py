"""Tests for the DeepAgents runner facade."""

from collections.abc import AsyncIterator

from capybara.agent.deep_runtime import DeepAgentRunner, RunnerEvent


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
