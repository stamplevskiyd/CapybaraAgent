from collections.abc import AsyncIterator

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model
from pydantic_ai.models.test import TestModel

from capybara.agent.base import BaseAgent, ReplyAccumulator, StreamedText
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
    ) -> AsyncIterator[StreamedText]:
        """Raise immediately; the trailing yield only marks this as a generator."""
        raise RuntimeError(self._message)
        yield StreamedText(text="")  # pragma: no cover


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
    ) -> AsyncIterator[StreamedText]:
        """Yield one accumulated delta, then raise to abort the stream."""
        acc.text += self._partial
        yield StreamedText(text=self._partial)
        raise RuntimeError(self._message)


class SlowStreamAgent(FakeAgent):
    """FakeAgent whose stream yields after an await, so concurrent turns overlap.

    The ``asyncio.sleep`` hands control back to the event loop mid-turn, making
    interleaving of two same-chat requests observable in tests.
    """

    async def stream_reply(  # type: ignore[override]
        self,
        model_name: str,
        user_content: str,
        history,  # type: ignore[no-untyped-def]
        acc: ReplyAccumulator,
        tools=(),  # type: ignore[no-untyped-def]
    ):
        """Sleep to yield the loop, then emit the configured text as one delta."""
        import asyncio

        await asyncio.sleep(0.05)
        acc.text += self._output_text
        yield StreamedText(text=self._output_text)
        acc.model = "test"

    async def run_structured[T](  # type: ignore[override]
        self, model_name: str, system_prompt: str, user_content: str, output_type: type[T]
    ) -> T:
        """Return empty structured output so post-turn auto-capture cleanly finds nothing."""
        model = TestModel(custom_output_args={"facts": []}, call_tools=[])
        agent: Agent[None, T] = Agent(model, system_prompt=system_prompt, output_type=output_type)
        result = await agent.run(user_content)
        return result.output


class StubMemoryAgent(FakeAgent):
    """FakeAgent with a fixed embedding map and canned structured extraction output.

    ``embeddings`` maps input text → vector (unknown texts get a fixed non-zero vector so
    cosine distance is always defined). ``extracted`` is the dict fed to the extraction
    output tool, e.g. ``{"facts": [{"content": "...", "category": "personal"}]}``.

    Implementation note: ``_build_model`` always returns a text-output TestModel so
    ``stream_reply`` and ``generate_title`` work correctly.  ``run_structured`` is
    overridden to build a separate TestModel configured with ``custom_output_args`` so
    extraction returns the canned facts without interfering with the stream path.
    """

    def __init__(  # type: ignore[no-untyped-def]
        self,
        settings,
        *,
        output_text="Ответ",
        embeddings=None,
        extracted=None,
        models=("test-model",),
    ):
        super().__init__(settings, output_text=output_text, models=models)
        self._embeddings = embeddings or {}
        self._extracted = extracted or {"facts": []}

    async def embed(self, texts):  # type: ignore[no-untyped-def]
        return [self._embeddings.get(t, [0.0] * 767 + [1.0]) for t in texts]

    def _build_model(self, name: str) -> Model:
        # Always return a text-output model; run_structured uses its own model instance.
        return TestModel(custom_output_text=self._output_text, call_tools=[])

    async def run_structured[T](  # type: ignore[override]
        self, model_name: str, system_prompt: str, user_content: str, output_type: type[T]
    ) -> T:
        """Return canned structured extraction output via a dedicated TestModel."""
        model = TestModel(custom_output_args=self._extracted, call_tools=[])
        agent: Agent[None, T] = Agent(model, system_prompt=system_prompt, output_type=output_type)
        result = await agent.run(user_content)
        return result.output


class ToolCallingFakeAgent(FakeAgent):
    """FakeAgent whose TestModel calls every registered tool — for tool-registration tests."""

    def _build_model(self, name: str) -> Model:
        return TestModel(custom_output_text=self._output_text)  # call_tools defaults to "all"


class EmptyReplyAgent(FakeAgent):
    """Faithfully simulate a successful but empty model reply.

    ``TestModel("")`` cannot represent an empty-successful reply under ``agent.iter()``:
    it produces no output and the agent graph raises ``UnexpectedModelBehavior``.
    This fake overrides ``stream_reply`` to yield zero events and return normally,
    leaving ``acc.text == ""`` and setting ``acc.model = "test"`` so
    ``ChatService.stream_turn`` completes and emits ``Done(message_id=None)``.
    """

    async def stream_reply(
        self,
        model_name: str,
        user_content: str,
        history: list[ModelMessage],
        acc: ReplyAccumulator,
        tools=(),  # type: ignore[no-untyped-def]
    ) -> AsyncIterator[StreamedText]:
        """Yield zero events; return normally to model a successful empty reply."""
        acc.model = "test"
        return
        yield StreamedText(text="")  # pragma: no cover


class ScriptedToolAgent(FakeAgent):
    """Agent whose stream yields a fixed tool-call → tool-result → text sequence.

    Lets service and router tests exercise tool-event mapping and persistence
    deterministically, independent of TestModel's tool-calling behaviour.
    """

    async def stream_reply(  # type: ignore[override]
        self,
        model_name: str,
        user_content: str,
        history,  # type: ignore[no-untyped-def]
        acc: ReplyAccumulator,
        tools=(),  # type: ignore[no-untyped-def]
    ):
        """Yield one tool call, its result, then the configured text."""
        from capybara.agent.base import StreamedToolCall, StreamedToolResult

        args = {"query": "любимое"}
        acc.tool_calls.append({"id": "call-1", "name": "recall", "args": args, "result": None})
        yield StreamedToolCall(id="call-1", name="recall", args=args)
        acc.tool_calls[0]["result"] = "- [personal] походы"
        yield StreamedToolResult(id="call-1", result="- [personal] походы")
        acc.text += self._output_text
        yield StreamedText(text=self._output_text)
        acc.model = "test"
