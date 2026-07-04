from collections.abc import AsyncIterator

from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model
from pydantic_ai.models.test import TestModel

from capybara.agent.base import BaseAgent, ReplyAccumulator
from capybara.config import Settings


class FakeAgent(BaseAgent):
    def __init__(self, settings: Settings, output_text: str) -> None:
        self._output_text = output_text
        super().__init__(settings)

    def _create_model(self, settings: Settings) -> Model:
        return TestModel(custom_output_text=self._output_text)


class RaisingAgent(BaseAgent):
    """Agent whose stream raises mid-reply — used to test SSE error handling."""

    def __init__(self, settings: Settings, message: str) -> None:
        self._message = message
        super().__init__(settings)

    def _create_model(self, settings: Settings) -> Model:
        return TestModel()

    async def stream_reply(
        self,
        user_content: str,
        history: list[ModelMessage],
        acc: ReplyAccumulator,
    ) -> AsyncIterator[str]:
        """Raise immediately; the trailing yield only marks this as a generator."""
        raise RuntimeError(self._message)
        yield ""  # pragma: no cover


class PartialThenFailAgent(BaseAgent):
    """Agent that streams one partial delta and then fails — models a mid-reply error."""

    def __init__(self, settings: Settings, partial: str, message: str) -> None:
        self._partial = partial
        self._message = message
        super().__init__(settings)

    def _create_model(self, settings: Settings) -> Model:
        return TestModel()

    async def stream_reply(
        self,
        user_content: str,
        history: list[ModelMessage],
        acc: ReplyAccumulator,
    ) -> AsyncIterator[str]:
        """Yield one accumulated delta, then raise to abort the stream."""
        acc.text += self._partial
        yield self._partial
        raise RuntimeError(self._message)
