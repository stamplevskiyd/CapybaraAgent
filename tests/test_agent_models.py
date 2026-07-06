"""Tests for provider model listing and availability validation."""

import httpx
import pytest

from capybara.agent import ModelProviderError, ModelUnavailableError, OllamaAgent
from capybara.config import Settings


def _agent_with_transport(settings: Settings, handler) -> OllamaAgent:  # type: ignore[no-untyped-def]
    agent = OllamaAgent(settings)
    agent._client_factory = lambda: httpx.AsyncClient(  # type: ignore[attr-defined]
        transport=httpx.MockTransport(handler)
    )
    return agent


async def test_list_models_returns_names(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(
            200,
            json={"models": [{"name": "llama3.1:8b"}, {"name": "qwen2.5:14b"}]},
        )

    agent = _agent_with_transport(settings, handler)
    assert await agent.list_models() == ["llama3.1:8b", "qwen2.5:14b"]


async def test_list_models_raises_provider_error_when_unreachable(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    agent = _agent_with_transport(settings, handler)
    with pytest.raises(ModelProviderError):
        await agent.list_models()


async def test_ensure_available_rejects_unset_and_unknown(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}]})

    agent = _agent_with_transport(settings, handler)
    with pytest.raises(ModelUnavailableError):
        await agent.ensure_available(None)
    with pytest.raises(ModelUnavailableError):
        await agent.ensure_available("ghost:1b")
    await agent.ensure_available("llama3.1:8b")  # no raise


async def test_ensure_available_returns_the_validated_name(settings: Settings) -> None:
    """ensure_available narrows str | None to str by returning the validated name.

    Callers can then use the return value directly instead of re-asserting that the
    optional model is not None after the call.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}]})

    agent = _agent_with_transport(settings, handler)
    assert await agent.ensure_available("llama3.1:8b") == "llama3.1:8b"
