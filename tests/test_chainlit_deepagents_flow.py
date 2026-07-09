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
