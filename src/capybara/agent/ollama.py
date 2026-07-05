"""Ollama-backed agent using the OpenAI-compatible API and the native tags endpoint."""

from collections.abc import Sequence

import httpx
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from capybara.agent.base import BaseAgent, ModelProviderError


class OllamaAgent(BaseAgent):
    """Agent that targets an Ollama server via OpenAI-compatible endpoints."""

    #: Overridable in tests to inject a mock transport.
    def _client_factory(self) -> httpx.AsyncClient:
        """Create the httpx client used to query Ollama's native API."""
        return httpx.AsyncClient(timeout=10.0)

    async def list_models(self) -> list[str]:
        """Return installed model names from Ollama's ``/api/tags`` endpoint.

        Raises:
            ModelProviderError: If Ollama cannot be reached, returns an error status,
                or returns a body that is not the expected JSON shape.
        """
        url = f"{self._settings.ollama_base_url}/api/tags"
        try:
            async with self._client_factory() as client:
                response = await client.get(url)
                response.raise_for_status()
            data = response.json()
            return [entry["name"] for entry in data.get("models", [])]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise ModelProviderError(self._settings.ollama_base_url) from exc

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
            ModelProviderError: If Ollama cannot be reached or returns an unexpected shape.
        """
        url = f"{self._settings.ollama_base_url}/api/embed"
        payload = {"model": self._settings.embedding_model, "input": list(texts)}
        try:
            async with self._client_factory() as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
            data = response.json()
            return [list(vector) for vector in data["embeddings"]]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise ModelProviderError(self._settings.ollama_base_url) from exc
