from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from capybara.db.models import Message


@dataclass
class ReplyAccumulator:
    text: str = ""
    usage: dict[str, Any] | None = None
    model: str | None = None


def to_model_messages(messages: Sequence[Message]) -> list[ModelMessage]:
    history: list[ModelMessage] = []
    for message in messages:
        if message.role == "user":
            history.append(ModelRequest(parts=[UserPromptPart(content=message.content)]))
        elif message.role == "assistant":
            history.append(ModelResponse(parts=[TextPart(content=message.content)]))
    return history


async def stream_reply(
    agent: Agent[None, str],
    user_content: str,
    history: list[ModelMessage],
    acc: ReplyAccumulator,
) -> AsyncIterator[str]:
    async with agent.run_stream(user_content, message_history=history) as result:
        async for text in result.stream_text(delta=True):
            acc.text += text
            yield text
        run_usage = result.usage
        acc.usage = (
            {"total_tokens": run_usage.total_tokens} if run_usage.has_values() else None
        )
        acc.model = result.response.model_name
