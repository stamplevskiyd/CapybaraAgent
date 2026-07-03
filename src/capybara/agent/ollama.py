"""Ollama-backed agent using the OpenAI-compatible API."""

from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from capybara.agent.base import BaseAgent
from capybara.config import Settings


class OllamaAgent(BaseAgent):
    """Agent that targets an Ollama server via OpenAI-compatible endpoints."""

    def _create_model(self, settings: Settings) -> Model:
        return OpenAIChatModel(
            settings.default_model,
            provider=OpenAIProvider(
                base_url=f"{settings.ollama_base_url}/v1",
                api_key="ollama",  # Ollama ignores the key; required by the client.
            ),
        )
