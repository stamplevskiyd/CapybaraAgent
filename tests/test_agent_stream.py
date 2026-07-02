from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from capybara.agent.stream import ReplyAccumulator, stream_reply, to_model_messages
from capybara.db.models import Message


async def test_stream_reply_yields_deltas_and_fills_accumulator() -> None:
    agent: Agent[None, str] = Agent(TestModel(custom_output_text="Привет, Роман"))
    acc = ReplyAccumulator()
    chunks = [delta async for delta in stream_reply(agent, "Привет", [], acc)]
    assert "".join(chunks) == "Привет, Роман"
    assert acc.text == "Привет, Роман"


def test_to_model_messages_maps_roles() -> None:
    msgs = [
        Message(chat_id=None, role="user", content="hi"),  # type: ignore[arg-type]
        Message(chat_id=None, role="assistant", content="hello"),  # type: ignore[arg-type]
    ]
    history = to_model_messages(msgs)
    assert len(history) == 2
