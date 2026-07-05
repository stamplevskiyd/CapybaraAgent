import httpx
import pytest

from capybara.agent.base import EmbeddingModelUnavailableError, ModelProviderError
from capybara.agent.ollama import OllamaAgent
from capybara.config import Settings


def _settings() -> Settings:
    return Settings(jwt_secret="x" * 32, embedding_model="nomic-embed-text")


async def test_ollama_embed_posts_and_parses() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = httpx.Request.read(request).decode()
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2], [0.3, 0.4]]})

    class MockedOllama(OllamaAgent):
        def _client_factory(self) -> httpx.AsyncClient:
            return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    agent = MockedOllama(_settings())
    vectors = await agent.embed(["hello", "world"])

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert captured["url"].endswith("/api/embed")  # type: ignore[union-attr]
    assert "nomic-embed-text" in captured["json"]  # type: ignore[operator]


async def test_ollama_embed_404_raises_embedding_model_unavailable() -> None:
    """A 404 (model not pulled) surfaces an actionable error, not a misleading 'unreachable'."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404, json={"error": 'model "nomic-embed-text" not found, try pulling it first'}
        )

    class MockedOllama(OllamaAgent):
        def _client_factory(self) -> httpx.AsyncClient:
            return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    agent = MockedOllama(_settings())
    with pytest.raises(EmbeddingModelUnavailableError) as exc_info:
        await agent.embed(["hi"])
    message = str(exc_info.value)
    assert "nomic-embed-text" in message
    assert "ollama pull" in message.lower()


async def test_ollama_embed_connection_error_raises_provider_error() -> None:
    """A genuine connection failure still surfaces ModelProviderError (unreachable)."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    class MockedOllama(OllamaAgent):
        def _client_factory(self) -> httpx.AsyncClient:
            return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    agent = MockedOllama(_settings())
    with pytest.raises(ModelProviderError):
        await agent.embed(["hi"])
