"""Ollama-backed agent using the OpenAI-compatible API and the native tags endpoint."""

import asyncio
from collections.abc import Sequence

import httpx
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from capybara.agent.base import (
    BaseAgent,
    EmbeddingDimensionError,
    EmbeddingModelUnavailableError,
    ModelProviderError,
)


class OllamaAgent(BaseAgent):
    """Agent that targets an Ollama server via OpenAI-compatible endpoints."""

    #: Overridable in tests to inject a mock transport.
    def _client_factory(self) -> httpx.AsyncClient:
        """Create the httpx client used to query Ollama's native API."""
        return httpx.AsyncClient(timeout=10.0)

    async def list_models(self) -> list[str]:
        """Return installed, chat-capable model names from Ollama.

        Names come from ``/api/tags``; each is then checked against ``/api/show``, and a
        model is kept unless its reported ``capabilities`` are present and lack
        ``"completion"``. This drops embedding-only models (e.g. ``nomic-embed-text``),
        which cannot serve chat, while keeping any model whose capabilities Ollama does
        not report (fail-open).

        Raises:
            ModelProviderError: If Ollama cannot be reached, returns an error status,
                or returns a body that is not the expected JSON shape.
        """
        base = self._settings.ollama_base_url
        try:
            async with self._client_factory() as client:
                response = await client.get(f"{base}/api/tags")
                response.raise_for_status()
                names = [entry["name"] for entry in response.json().get("models", [])]
                chat_capable = await asyncio.gather(
                    *(self._supports_chat(client, name) for name in names)
                )
            return [name for name, keep in zip(names, chat_capable, strict=True) if keep]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise ModelProviderError(base) from exc

    async def _supports_chat(self, client: httpx.AsyncClient, name: str) -> bool:
        """Return whether *name* can serve chat, per Ollama's ``/api/show`` capabilities.

        Fails open: a model whose response omits ``capabilities`` is treated as
        chat-capable. Only a present list that lacks ``"completion"`` excludes it.

        Raises:
            httpx.HTTPError: If the ``/api/show`` request cannot complete, so the caller
                surfaces it as a provider outage rather than silently dropping models.
        """
        url = f"{self._settings.ollama_base_url}/api/show"
        response = await client.post(url, json={"model": name})
        response.raise_for_status()
        capabilities = response.json().get("capabilities")
        if capabilities is None:
            return True
        return "completion" in capabilities

    def _build_model(self, name: str) -> Model:
        """Build an OpenAI-compatible model pointed at the Ollama server."""
        return OpenAIChatModel(
            name,
            provider=OpenAIProvider(
                base_url=f"{self._settings.ollama_base_url}/v1",
                api_key="ollama",  # Ollama ignores the key; required by the client.
            ),
        )

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return embeddings for *texts* via Ollama's native ``/api/embed`` endpoint.

        Raises:
            EmbeddingModelUnavailableError: If Ollama answers 404 — the server is up but
                the embedding model is not pulled (the common, actionable failure).
            ModelProviderError: If Ollama cannot be reached, or returns any other error
                status or an unexpected body shape.
        """
        url = f"{self._settings.ollama_base_url}/api/embed"
        payload = {"model": self._settings.embedding_model, "input": list(texts)}
        try:
            async with self._client_factory() as client:
                response = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            # Request never completed → server genuinely unreachable.
            raise ModelProviderError(self._settings.ollama_base_url) from exc
        if response.status_code == 404:
            # Ollama responded — the embedding model just isn't installed.
            raise EmbeddingModelUnavailableError(self._settings.embedding_model)
        try:
            response.raise_for_status()
            data = response.json()
            vectors = [list(vector) for vector in data["embeddings"]]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise ModelProviderError(self._settings.ollama_base_url) from exc
        expected = self._settings.embedding_dimensions
        for vector in vectors:
            if len(vector) != expected:
                raise EmbeddingDimensionError(expected, len(vector), self._settings.embedding_model)
        return vectors
