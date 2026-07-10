"""Agent abstractions for LLM interaction."""

from capybara.agent.errors import (
    EmbeddingDimensionError,
    EmbeddingModelUnavailableError,
    ModelProviderError,
)
from capybara.agent.model_registry import ModelRegistry

__all__ = [
    "EmbeddingDimensionError",
    "EmbeddingModelUnavailableError",
    "ModelProviderError",
    "ModelRegistry",
]
