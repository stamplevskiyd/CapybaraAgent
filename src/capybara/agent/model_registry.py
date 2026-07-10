"""Provider-agnostic model listing and embedding over Ollama."""

import asyncio

import httpx
from langchain_ollama import ChatOllama

from capybara.agent.errors import (
    EmbeddingDimensionError,
    EmbeddingModelUnavailableError,
    ModelProviderError,
)
from capybara.config import Settings


class ModelRegistry:
    """List and build chat models, and embed text, against local-first Ollama.

    The single provider abstraction for the app: the DeepAgents runtime builds chat models
    here, and the memory/model REST paths list models and embed text through it.
    """

    def __init__(self, settings: Settings) -> None:
        """Store settings used to reach Ollama."""
        self._settings = settings

    def _client_factory(self) -> httpx.AsyncClient:
        """Create the httpx client used to query Ollama's native API (overridable in tests)."""
        return httpx.AsyncClient(timeout=10.0)

    async def list_models(self) -> list[str]:
        """Return chat-capable Ollama model names.

        Raises:
            ModelProviderError: If Ollama cannot be reached or returns an unexpected shape.
        """
        base = self._settings.ollama_base_url
        try:
            async with self._client_factory() as client:
                response = await client.get(f"{base}/api/tags")
                response.raise_for_status()
                names = [str(entry["name"]) for entry in response.json()["models"]]
                flags = await asyncio.gather(*(self._supports_chat(client, name) for name in names))
            return [name for name, keep in zip(names, flags, strict=True) if keep]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise ModelProviderError(base) from exc

    async def _supports_chat(self, client: httpx.AsyncClient, name: str) -> bool:
        """Return whether an Ollama model can serve chat completions (fail-open)."""
        response = await client.post(
            f"{self._settings.ollama_base_url}/api/show",
            json={"model": name},
        )
        response.raise_for_status()
        capabilities = response.json().get("capabilities")
        return capabilities is None or "completion" in capabilities

    def chat_model(self, name: str) -> ChatOllama:
        """Build a LangChain Ollama chat model."""
        return ChatOllama(model=name, base_url=self._settings.ollama_base_url)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text via Ollama's ``/api/embed``.

        Raises:
            EmbeddingModelUnavailableError: If Ollama answers 404 — the server is up but the
                embedding model is not pulled (the common, actionable failure).
            EmbeddingDimensionError: If a returned vector has the wrong dimensionality.
            ModelProviderError: If Ollama cannot be reached, or returns any other error
                status or an unexpected body shape.
        """
        base = self._settings.ollama_base_url
        payload = {"model": self._settings.embedding_model, "input": list(texts)}
        try:
            async with self._client_factory() as client:
                response = await client.post(f"{base}/api/embed", json=payload)
        except httpx.HTTPError as exc:
            raise ModelProviderError(base) from exc
        if response.status_code == 404:
            raise EmbeddingModelUnavailableError(self._settings.embedding_model)
        try:
            response.raise_for_status()
            vectors = [list(vector) for vector in response.json()["embeddings"]]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise ModelProviderError(base) from exc
        expected = self._settings.embedding_dimensions
        for vector in vectors:
            if len(vector) != expected:
                raise EmbeddingDimensionError(expected, len(vector), self._settings.embedding_model)
        return vectors
