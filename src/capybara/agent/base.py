"""Abstract base agent and error types for LLM interaction."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from pydantic_ai import Agent
from pydantic_ai.models import Model

from capybara.config import Settings


class ModelUnavailableError(Exception):
    """Raised when a chat's model is unset or not present in the provider's live list."""

    def __init__(self, model_name: str | None, available: list[str]) -> None:
        """Record the offending model name and the list of currently available models."""
        self.model_name = model_name
        self.available = available
        super().__init__(f"Model {model_name!r} is not available. Select an installed model.")


class ModelProviderError(Exception):
    """Raised when the model provider (Ollama) cannot be reached at all."""

    def __init__(self, url: str) -> None:
        """Record the provider base URL that could not be reached."""
        self.url = url
        super().__init__(f"Ollama unreachable at {url}")


class EmbeddingModelUnavailableError(Exception):
    """Raised when the provider is reachable but the embedding model is not installed.

    Distinct from ModelProviderError (server down): here Ollama answered with a
    model-not-found response, so the actionable fix is to pull the model.
    """

    def __init__(self, model_name: str) -> None:
        """Record the missing embedding model and how to install it."""
        self.model_name = model_name
        super().__init__(
            f"Embedding model {model_name!r} is not available in Ollama. "
            f"Pull it first: `ollama pull {model_name}`."
        )


class EmbeddingDimensionError(Exception):
    """Raised when the provider returns embeddings of an unexpected dimensionality.

    Distinct from a provider outage: Ollama answered, but the vectors do not match the
    dimensionality the ``facts.embedding`` column expects (usually because a different
    embedding model was configured). Caught early so the failure is an actionable config
    error, not a late 500 on the DB write.
    """

    def __init__(self, expected: int, actual: int, model_name: str) -> None:
        """Record the expected vs actual dimensions and the embedding model in use."""
        self.expected = expected
        self.actual = actual
        self.model_name = model_name
        super().__init__(
            f"Embedding model {model_name!r} returned {actual}-dim vectors, "
            f"but {expected} dimensions are expected. Check the configured embedding model."
        )


class BaseAgent(ABC):
    """Abstract provider abstraction: list models, build a model, embed, and validate."""

    def __init__(self, settings: Settings) -> None:
        """Store settings; models are built per-turn, not bound at construction."""
        self._settings = settings

    @abstractmethod
    async def list_models(self) -> list[str]:
        """Return the names of models currently available from the provider."""
        ...

    @abstractmethod
    def _build_model(self, name: str) -> Model:
        """Build a pydantic-ai model for the given model name."""
        ...

    @abstractmethod
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""
        ...

    async def run_structured[T](
        self, model_name: str, system_prompt: str, user_content: str, output_type: type[T]
    ) -> T:
        """Run a one-shot agent that returns a validated structured result.

        Generic over the output schema so callers own their own extraction types; the
        agent layer stays domain-agnostic.
        """
        agent: Agent[None, T] = Agent(
            self._build_model(model_name),
            system_prompt=system_prompt,
            output_type=output_type,
        )
        result = await agent.run(user_content)
        return result.output

    async def ensure_available(self, model_name: str | None) -> str:
        """Return *model_name* if it is set and present in the provider's live list.

        Returning the validated name narrows ``str | None`` to ``str`` for callers,
        so no post-call assertion is needed.

        Raises:
            ModelUnavailableError: If *model_name* is ``None`` or absent from the list.
            ModelProviderError: If the provider cannot be reached (from ``list_models``).
        """
        if not model_name:
            raise ModelUnavailableError(model_name, [])
        available = await self.list_models()
        if model_name not in available:
            raise ModelUnavailableError(model_name, available)
        return model_name
