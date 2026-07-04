"""Ollama-backed agent using the OpenAI-compatible API and the native tags endpoint."""

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
            ModelProviderError: If Ollama cannot be reached or returns an error status.
        """
        url = f"{self._settings.ollama_base_url}/api/tags"
        try:
            async with self._client_factory() as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ModelProviderError(self._settings.ollama_base_url) from exc
        data = response.json()
        return [entry["name"] for entry in data.get("models", [])]

    def _build_model(self, name: str) -> Model:
        """Build an OpenAI-compatible model pointed at the Ollama server."""
        return OpenAIChatModel(
            name,
            provider=OpenAIProvider(
                base_url=f"{self._settings.ollama_base_url}/v1",
                api_key="ollama",  # Ollama ignores the key; required by the client.
            ),
        )
