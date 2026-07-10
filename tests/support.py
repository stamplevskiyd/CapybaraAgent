from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.test import TestModel

from capybara.agent.base import BaseAgent
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


class StubMemoryAgent(FakeAgent):
    """FakeAgent with a fixed embedding map and canned structured extraction output.

    ``embeddings`` maps input text → vector (unknown texts get a fixed non-zero vector so
    cosine distance is always defined). ``extracted`` is the dict fed to the extraction
    output tool, e.g. ``{"facts": [{"content": "...", "category": "personal"}]}``.

    ``run_structured`` is overridden to build a separate TestModel configured with
    ``custom_output_args`` so extraction returns the canned facts.
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
