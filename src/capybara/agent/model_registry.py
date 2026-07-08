"""Provider-agnostic model listing and construction for the DeepAgents runtime."""

import asyncio

import httpx
from langchain_ollama import ChatOllama, OllamaEmbeddings

from capybara.config import Settings


class ModelRegistry:
    """List and build local-first LLM and embedding providers."""

    def __init__(self, settings: Settings) -> None:
        """Store settings used to reach Ollama."""
        self._settings = settings

    async def list_models(self) -> list[str]:
        """Return chat-capable Ollama model names."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self._settings.ollama_base_url}/api/tags")
            response.raise_for_status()
            names = self._model_names(response.json())
            flags = await asyncio.gather(*(self._supports_chat(client, name) for name in names))
        return [name for name, keep in zip(names, flags, strict=True) if keep]

    async def _supports_chat(self, client: httpx.AsyncClient, name: str) -> bool:
        """Return whether an Ollama model can serve chat completions."""
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

    def embeddings(self) -> OllamaEmbeddings:
        """Build LangChain Ollama embeddings."""
        return OllamaEmbeddings(
            model=self._settings.embedding_model,
            base_url=self._settings.ollama_base_url,
        )

    def _model_names(self, payload: object) -> list[str]:
        """Extract model names from Ollama's native tags response."""
        if not isinstance(payload, dict):
            return []
        models = payload.get("models")
        if not isinstance(models, list):
            return []
        names: list[str] = []
        for entry in models:
            if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                names.append(entry["name"])
        return names
