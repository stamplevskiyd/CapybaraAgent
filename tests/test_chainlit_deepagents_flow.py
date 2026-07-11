"""Tests for the Chainlit-to-DeepAgents message flow."""

from collections.abc import AsyncIterator

from capybara.agent.deep_runtime import RunnerEvent
from capybara.chainlit_app import stream_agent_message


class FakeRunner:
    """Runner fake that streams one text event."""

    async def stream(
        self,
        content: str,
        *,
        model: str,
        thread_id: str,
        mode: str = "smart",
    ) -> AsyncIterator[RunnerEvent]:
        """Yield a deterministic response."""
        assert content == "Hello"
        assert model == "llama3.1"
        assert thread_id == "thread-1"
        yield RunnerEvent(kind="text", content="Hi")


class FakeMessageSink:
    """Chainlit message fake that records streamed tokens and send calls."""

    def __init__(self) -> None:
        """Initialize an empty sink."""
        self.tokens: list[str] = []
        self.sent = False

    async def stream_token(self, token: str) -> None:
        """Record one streamed token."""
        self.tokens.append(token)

    async def send(self) -> None:
        """Record that the message was finalized."""
        self.sent = True


class ToolRunner:
    """Runner fake that streams a tool lifecycle around a text token."""

    async def stream(
        self,
        content: str,
        *,
        model: str,
        thread_id: str,
        mode: str = "smart",
    ) -> AsyncIterator[RunnerEvent]:
        """Yield tool start/end events and a final text token."""
        yield RunnerEvent(
            kind="tool_start", name="recall", payload={"run_id": "r1", "input": {"query": "x"}}
        )
        yield RunnerEvent(
            kind="tool_end", name="recall", payload={"run_id": "r1", "output": "facts"}
        )
        yield RunnerEvent(kind="text", content="done")


class FakeStep:
    """Chainlit step fake that records its input/output and lifecycle calls."""

    def __init__(self, name: str) -> None:
        """Record the step name and initialize its state."""
        self.name = name
        self.input: object = None
        self.output: object = None
        self.sent = False
        self.updated = False

    async def send(self) -> None:
        """Record that the step was opened."""
        self.sent = True

    async def update(self) -> None:
        """Record that the step was finalized."""
        self.updated = True


async def test_stream_agent_message_streams_runner_text() -> None:
    """The Chainlit helper streams runner text into the response sink."""
    sink = FakeMessageSink()

    await stream_agent_message(
        runner=FakeRunner(),
        content="Hello",
        model="llama3.1",
        thread_id="thread-1",
        response=sink,
    )

    assert sink.tokens == ["Hi"]
    assert sink.sent is True


async def test_stream_agent_message_renders_tool_calls_as_steps() -> None:
    """Tool start/end events open a step, then finalize it with the tool's output."""
    sink = FakeMessageSink()
    steps: list[FakeStep] = []

    def new_step(name: str) -> FakeStep:
        step = FakeStep(name)
        steps.append(step)
        return step

    await stream_agent_message(
        runner=ToolRunner(),
        content="Hello",
        model="llama3.1",
        thread_id="thread-1",
        response=sink,
        new_step=new_step,
    )

    assert len(steps) == 1
    step = steps[0]
    assert step.name == "recall"
    assert step.input == {"query": "x"}
    assert step.sent is True
    assert step.output == "facts"
    assert step.updated is True
    assert sink.tokens == ["done"]
    assert sink.sent is True
