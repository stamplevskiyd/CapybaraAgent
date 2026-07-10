from pydantic import BaseModel

from capybara.agent.model_registry import ModelRegistry
from capybara.config import Settings


class FakeAgent(ModelRegistry):
    """ModelRegistry stub with a fixed model list and canned structured/embedding output."""

    def __init__(
        self, settings: Settings, output_text: str, models: tuple[str, ...] = ("test-model",)
    ) -> None:
        self._output_text = output_text
        self._models = list(models)
        super().__init__(settings)

    async def list_models(self) -> list[str]:
        return list(self._models)

    async def embed(self, texts):  # type: ignore[no-untyped-def]
        return [[0.1] * 768 for _ in texts]

    async def run_structured[T: BaseModel](
        self, model_name: str, system_prompt: str, user_content: str, output_type: type[T]
    ) -> T:
        return output_type()


class StubMemoryAgent(FakeAgent):
    """FakeAgent with a fixed embedding map and canned structured extraction output.

    ``embeddings`` maps input text → vector (unknown texts get a fixed non-zero vector so
    cosine distance is always defined). ``extracted`` is the dict fed to the extraction
    output type, e.g. ``{"facts": [{"content": "...", "category": "personal"}]}``.
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

    async def run_structured[T: BaseModel](
        self, model_name: str, system_prompt: str, user_content: str, output_type: type[T]
    ) -> T:
        """Return canned structured extraction output validated against *output_type*."""
        return output_type.model_validate(self._extracted)


class ToolCallingFakeAgent(FakeAgent):
    """FakeAgent kept as a distinct type for tool-registration tests."""
