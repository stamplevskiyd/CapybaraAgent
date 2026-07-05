from collections.abc import AsyncIterator

from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model
from pydantic_ai.models.test import TestModel

from capybara.agent.base import BaseAgent, ReplyAccumulator
from capybara.config import Settings


class FakeAgent(BaseAgent):
    """Agent backed by pydantic-ai TestModel with a fixed, configurable model list."""

    def __init__(
        self, settings: Settings, output_text: str, models: tuple[str, ...] = ("test-model",)
    ) -> None:
        self._output_text = output_text
        self._models = list(models)
        super().__init__(settings)

    async def list_models(self) -> list[str]:
        return list(self._models)

    def _build_model(self, name: str) -> Model:
        return TestModel(custom_output_text=self._output_text, call_tools=[])

    async def embed(self, texts):  # type: ignore[no-untyped-def]
        return [[0.1] * 768 for _ in texts]


class RaisingAgent(BaseAgent):
    """Agent whose stream raises mid-reply — used to test SSE error handling."""

    def __init__(self, settings: Settings, message: str) -> None:
        self._message = message
        super().__init__(settings)

    async def list_models(self) -> list[str]:
        return ["test-model"]

    def _build_model(self, name: str) -> Model:
        return TestModel()

    async def embed(self, texts):  # type: ignore[no-untyped-def]
        return [[0.1] * 768 for _ in texts]

    async def stream_reply(
        self,
        model_name: str,
        user_content: str,
        history: list[ModelMessage],
        acc: ReplyAccumulator,
        tools=(),  # type: ignore[no-untyped-def]
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

    async def list_models(self) -> list[str]:
        return ["test-model"]

    def _build_model(self, name: str) -> Model:
        return TestModel()

    async def embed(self, texts):  # type: ignore[no-untyped-def]
        return [[0.1] * 768 for _ in texts]

    async def stream_reply(
        self,
        model_name: str,
        user_content: str,
        history: list[ModelMessage],
        acc: ReplyAccumulator,
        tools=(),  # type: ignore[no-untyped-def]
    ) -> AsyncIterator[str]:
        """Yield one accumulated delta, then raise to abort the stream."""
        acc.text += self._partial
        yield self._partial
        raise RuntimeError(self._message)
