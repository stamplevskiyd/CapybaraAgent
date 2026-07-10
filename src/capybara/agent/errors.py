"""Provider (Ollama) error types shared by the model registry and its callers."""


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
