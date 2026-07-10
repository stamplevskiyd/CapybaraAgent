from capybara.agent.model_registry import ModelRegistry
from capybara.config import Settings


class FakeAgent(ModelRegistry):
    """ModelRegistry stub with a fixed model list and canned embeddings."""

    def __init__(self, settings: Settings, models: tuple[str, ...] = ("test-model",)) -> None:
        self._models = list(models)
        super().__init__(settings)

    async def list_models(self) -> list[str]:
        return list(self._models)

    async def embed(self, texts):  # type: ignore[no-untyped-def]
        return [[0.1] * 768 for _ in texts]


class StubMemoryAgent(FakeAgent):
    """FakeAgent with a fixed embedding map.

    ``embeddings`` maps input text → vector (unknown texts get a fixed non-zero vector so
    cosine distance is always defined).
    """

    def __init__(self, settings, *, embeddings=None, models=("test-model",)):  # type: ignore[no-untyped-def]
        super().__init__(settings, models=models)
        self._embeddings = embeddings or {}

    async def embed(self, texts):  # type: ignore[no-untyped-def]
        return [self._embeddings.get(t, [0.0] * 767 + [1.0]) for t in texts]
