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
        self._client: httpx.AsyncClient | None = None

    def _client_factory(self) -> httpx.AsyncClient:
        """Create the httpx client used to query Ollama's native API (overridable in tests)."""
        return httpx.AsyncClient(timeout=10.0)

    def _http(self) -> httpx.AsyncClient:
        """Return the shared client, creating it on first use.

        One pooled client per registry keeps connections to Ollama alive across the many
        small calls (embed per fact, show per model) instead of a TCP handshake each time.
        """
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    async def aclose(self) -> None:
        """Dispose the shared client (app shutdown); safe to call when never used."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def list_models(self) -> list[str]:
        """Return chat-capable Ollama model names.

        Raises:
            ModelProviderError: If Ollama cannot be reached or returns an unexpected shape.
        """
        base = self._settings.ollama_base_url
        try:
            client = self._http()
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
            response = await self._http().post(f"{base}/api/embed", json=payload)
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
