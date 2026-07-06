"""Tests for provider model listing and availability validation."""

import json

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


def _capability_handler(capabilities: dict[str, list[str] | None]):  # type: ignore[no-untyped-def]
    """Build a handler serving ``/api/tags`` plus a ``/api/show`` per model.

    ``capabilities`` maps model name to its capabilities list, or ``None`` to emit a
    ``/api/show`` body with no ``capabilities`` field (the older-Ollama, fail-open case).
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": n} for n in capabilities]})
        if request.url.path == "/api/show":
            name = json.loads(request.content)["model"]
            caps = capabilities[name]
            body: dict[str, list[str]] = {} if caps is None else {"capabilities": caps}
            return httpx.Response(200, json=body)
        raise AssertionError(f"unexpected path {request.url.path}")

    return handler


async def test_list_models_keeps_only_chat_capable(settings: Settings) -> None:
    handler = _capability_handler(
        {"llama3.1:8b": ["completion", "tools"], "nomic-embed-text": ["embedding"]}
    )
    agent = _agent_with_transport(settings, handler)
    assert await agent.list_models() == ["llama3.1:8b"]


async def test_list_models_keeps_model_without_capabilities_field(settings: Settings) -> None:
    """Fail open: a /api/show body lacking ``capabilities`` keeps the model."""
    handler = _capability_handler({"legacy-model": None})
    agent = _agent_with_transport(settings, handler)
    assert await agent.list_models() == ["legacy-model"]


async def test_list_models_raises_provider_error_when_show_unreachable(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}]})
        raise httpx.ConnectError("refused", request=request)

    agent = _agent_with_transport(settings, handler)
    with pytest.raises(ModelProviderError):
        await agent.list_models()


async def test_list_models_returns_names(settings: Settings) -> None:
    handler = _capability_handler({"llama3.1:8b": ["completion"], "qwen2.5:14b": ["completion"]})
    agent = _agent_with_transport(settings, handler)
    assert await agent.list_models() == ["llama3.1:8b", "qwen2.5:14b"]


async def test_list_models_raises_provider_error_when_unreachable(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    agent = _agent_with_transport(settings, handler)
    with pytest.raises(ModelProviderError):
        await agent.list_models()


async def test_ensure_available_rejects_unset_and_unknown(settings: Settings) -> None:
    agent = _agent_with_transport(settings, _capability_handler({"llama3.1:8b": ["completion"]}))
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
    agent = _agent_with_transport(settings, _capability_handler({"llama3.1:8b": ["completion"]}))
    assert await agent.ensure_available("llama3.1:8b") == "llama3.1:8b"
