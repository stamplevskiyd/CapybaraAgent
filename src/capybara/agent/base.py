"""Abstract base agent and reply accumulator for LLM streaming."""

from abc import ABC, abstractmethod
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
from pydantic_ai.models import Model

from capybara.config import Settings
from capybara.db.models import Message


@dataclass
class ReplyAccumulator:
    """Accumulate streaming text, usage stats, and model name from a single run."""

    text: str = ""
    usage: dict[str, Any] | None = None
    model: str | None = None


class BaseAgent(ABC):
    """Abstract base for LLM agents; provides message conversion and streaming."""

    def __init__(self, settings: Settings) -> None:
        self._agent: Agent[None, str] = Agent(self._create_model(settings))

    @abstractmethod
    def _create_model(self, settings: Settings) -> Model: ...

    @staticmethod
    def to_model_messages(messages: Sequence[Message]) -> list[ModelMessage]:
        """Convert DB Message rows to pydantic-ai ModelMessage history."""
        history: list[ModelMessage] = []
        for message in messages:
            if message.role == "user":
                history.append(ModelRequest(parts=[UserPromptPart(content=message.content)]))
            elif message.role == "assistant":
                history.append(ModelResponse(parts=[TextPart(content=message.content)]))
        return history

    async def stream_reply(
        self,
        user_content: str,
        history: list[ModelMessage],
        acc: ReplyAccumulator,
    ) -> AsyncIterator[str]:
        """Stream token deltas from the LLM and accumulate the full reply into acc."""
        async with self._agent.run_stream(user_content, message_history=history) as result:
            async for text in result.stream_text(delta=True):
                acc.text += text
                yield text
            run_usage = result.usage
            acc.usage = (
                {"total_tokens": run_usage.total_tokens} if run_usage.has_values() else None
            )
            acc.model = result.response.model_name
