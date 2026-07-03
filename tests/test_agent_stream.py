from pydantic_ai.messages import ModelRequest, ModelResponse

from capybara.agent.base import BaseAgent, ReplyAccumulator
from capybara.config import Settings
from capybara.db.models import Message
from support import FakeAgent


async def test_stream_reply_yields_deltas_and_fills_accumulator(
    settings: Settings,
) -> None:
    agent = FakeAgent(settings, "Привет, Роман")
    acc = ReplyAccumulator()
    chunks = [delta async for delta in agent.stream_reply("Привет", [], acc)]
    assert "".join(chunks) == "Привет, Роман"
    assert acc.text == "Привет, Роман"
    assert acc.model == "test"
    assert acc.usage == {"total_tokens": 54}


def test_to_model_messages_maps_roles() -> None:
    msgs = [
        Message(chat_id=None, role="user", content="hi"),  # type: ignore[arg-type]
        Message(chat_id=None, role="assistant", content="hello"),  # type: ignore[arg-type]
    ]
    history = BaseAgent.to_model_messages(msgs)
    assert len(history) == 2
    assert isinstance(history[0], ModelRequest)
    assert isinstance(history[1], ModelResponse)
