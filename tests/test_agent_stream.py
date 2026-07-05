import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse

from capybara.agent.base import BaseAgent, ReplyAccumulator, StreamedText
from capybara.config import Settings
from capybara.db.models import Message
from support import FakeAgent


async def test_stream_reply_yields_deltas_and_fills_accumulator(
    settings: Settings,
) -> None:
    agent = FakeAgent(settings, "Привет, Роман")
    acc = ReplyAccumulator()
    events = [e async for e in agent.stream_reply("test-model", "Привет", [], acc)]
    text = "".join(e.text for e in events if isinstance(e, StreamedText))
    assert text == "Привет, Роман"
    assert acc.text == "Привет, Роман"
    assert acc.model == "test"
    assert acc.usage is not None and acc.usage["total_tokens"] > 0
    assert acc.tool_calls == []


def test_to_model_messages_maps_roles() -> None:
    msgs = [
        Message(chat_id=None, role="user", content="hi"),  # type: ignore[arg-type]
        Message(chat_id=None, role="assistant", content="hello"),  # type: ignore[arg-type]
    ]
    history = BaseAgent.to_model_messages(msgs)
    assert len(history) == 2
    assert isinstance(history[0], ModelRequest)
    assert isinstance(history[1], ModelResponse)


def test_to_model_messages_rejects_unknown_role() -> None:
    """An unexpected role is a hard error, not a silently dropped message."""
    msgs = [Message(chat_id=None, role="system", content="be nice")]  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Unknown message role"):
        BaseAgent.to_model_messages(msgs)
