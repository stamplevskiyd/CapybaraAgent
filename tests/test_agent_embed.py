import httpx

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
