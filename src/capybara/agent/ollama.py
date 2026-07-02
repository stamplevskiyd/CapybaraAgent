from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from capybara.config import Settings


def build_agent(settings: Settings) -> "Agent[None, str]":
    model = OpenAIChatModel(
        settings.default_model,
        provider=OpenAIProvider(
            base_url=f"{settings.ollama_base_url}/v1",
            api_key="ollama",  # Ollama ignores the key; required by the client.
        ),
    )
    return Agent(model)
