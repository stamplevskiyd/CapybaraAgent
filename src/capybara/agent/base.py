"""Abstract base agent, error types, and reply accumulator for LLM streaming."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic_ai import Agent, Tool
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models import Model

from capybara.config import Settings
from capybara.db.models import Message

#: System prompt used to derive a short chat title from the first user message.
TITLE_SYSTEM_PROMPT = (
    "You generate a concise chat title of 3-5 words in the same language as the "
    "user's message. Reply with the title only — no quotes, no punctuation at the "
    "end, no preamble."
)

#: Maximum length of a generated/fallback title, matching ``chats.title``.
_TITLE_MAX = 200

#: System prompt for chat runs that carry tools — nudges the model to use recall.
CHAT_SYSTEM_PROMPT = (
    "You are a helpful assistant. Use the `recall` tool to search the user's "
    "long-term memory whenever the question depends on personal details, "
    "preferences, or context they may have shared earlier."
)


def _clean_title(raw: str, *, fallback: str) -> str:
    """Normalise a model-produced title; fall back to a truncation of *fallback* if empty.

    Takes the first line, strips surrounding quotes and whitespace, collapses inner
    whitespace, and truncates to ``_TITLE_MAX``. If nothing usable remains, returns the
    first line of *fallback* truncated the same way.
    """
    first_line = raw.strip().splitlines()[0] if raw.strip() else ""
    cleaned = " ".join(first_line.strip("\"'«»`“” \t").split())[:_TITLE_MAX]
    if cleaned:
        return cleaned
    fb_line = fallback.strip().splitlines()[0] if fallback.strip() else fallback.strip()
    return " ".join(fb_line.split())[:_TITLE_MAX]


class ModelUnavailableError(Exception):
    """Raised when a chat's model is unset or not present in the provider's live list."""

    def __init__(self, model_name: str | None, available: list[str]) -> None:
        """Record the offending model name and the list of currently available models."""
        self.model_name = model_name
        self.available = available
        super().__init__(f"Model {model_name!r} is not available. Select an installed model.")


class ModelProviderError(Exception):
    """Raised when the model provider (Ollama) cannot be reached at all."""

    def __init__(self, url: str) -> None:
        """Record the provider base URL that could not be reached."""
        self.url = url
        super().__init__(f"Ollama unreachable at {url}")


class EmbeddingModelUnavailableError(Exception):
    """Raised when the provider is reachable but the embedding model is not installed.

    Distinct from ModelProviderError (server down): here Ollama answered with a
    model-not-found response, so the actionable fix is to pull the model.
    """

    def __init__(self, model_name: str) -> None:
        """Record the missing embedding model and how to install it."""
        self.model_name = model_name
        super().__init__(
            f"Embedding model {model_name!r} is not available in Ollama. "
            f"Pull it first: `ollama pull {model_name}`."
        )


@dataclass
class ReplyAccumulator:
    """Accumulate streaming text, usage stats, and model name from a single run."""

    text: str = ""
    usage: dict[str, Any] | None = None
    model: str | None = None


class BaseAgent(ABC):
    """Abstract provider abstraction: list models, build a model by name, and stream."""

    def __init__(self, settings: Settings) -> None:
        """Store settings; models are built per-turn, not bound at construction."""
        self._settings = settings

    @abstractmethod
    async def list_models(self) -> list[str]:
        """Return the names of models currently available from the provider."""
        ...

    @abstractmethod
    def _build_model(self, name: str) -> Model:
        """Build a pydantic-ai model for the given model name."""
        ...

    @abstractmethod
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""
        ...

    async def run_structured[T](
        self, model_name: str, system_prompt: str, user_content: str, output_type: type[T]
    ) -> T:
        """Run a one-shot agent that returns a validated structured result.

        Generic over the output schema so callers own their own extraction types; the
        agent layer stays domain-agnostic.
        """
        agent: Agent[None, T] = Agent(
            self._build_model(model_name),
            system_prompt=system_prompt,
            output_type=output_type,
        )
        result = await agent.run(user_content)
        return result.output

    async def ensure_available(self, model_name: str | None) -> None:
        """Raise ModelUnavailableError if model_name is unset or not in the live list.

        Raises:
            ModelUnavailableError: If *model_name* is ``None`` or absent from the list.
            ModelProviderError: If the provider cannot be reached (from ``list_models``).
        """
        if not model_name:
            raise ModelUnavailableError(model_name, [])
        available = await self.list_models()
        if model_name not in available:
            raise ModelUnavailableError(model_name, available)

    @staticmethod
    def to_model_messages(messages: Sequence[Message]) -> list[ModelMessage]:
        """Convert DB Message rows to pydantic-ai ModelMessage history."""
        history: list[ModelMessage] = []
        for message in messages:
            if message.role == "user":
                history.append(ModelRequest(parts=[UserPromptPart(content=message.content)]))
            elif message.role == "assistant":
                history.append(ModelResponse(parts=[TextPart(content=message.content)]))
            else:
                raise ValueError(f"Unknown message role: {message.role!r}")
        return history

    async def stream_reply(
        self,
        model_name: str,
        user_content: str,
        history: list[ModelMessage],
        acc: ReplyAccumulator,
        tools: Sequence[Tool[None]] = (),
    ) -> AsyncIterator[str]:
        """Stream token deltas for the named model and accumulate the reply into acc.

        When *tools* are supplied the chat system prompt (with the recall nudge) is set;
        with no tools the prompt is left empty so behaviour is unchanged.
        """
        tool_list = list(tools)
        agent: Agent[None, str] = Agent(
            self._build_model(model_name),
            system_prompt=CHAT_SYSTEM_PROMPT if tool_list else (),
            tools=tool_list,
        )
        async with agent.run_stream(user_content, message_history=history) as result:
            async for text in result.stream_text(delta=True):
                acc.text += text
                yield text
            run_usage = result.usage
            acc.usage = {"total_tokens": run_usage.total_tokens} if run_usage.has_values() else None
            acc.model = result.response.model_name

    async def generate_title(self, model_name: str, first_user_message: str) -> str:
        """Ask the model for a short chat title; never raises.

        On any failure or empty output, falls back to a truncation of the user message,
        so the returned title is always at least as good as the default.
        """
        try:
            agent: Agent[None, str] = Agent(
                self._build_model(model_name), system_prompt=TITLE_SYSTEM_PROMPT
            )
            result = await agent.run(first_user_message)
            return _clean_title(result.output, fallback=first_user_message)
        except Exception:  # title generation must never break the reply flow
            return _clean_title("", fallback=first_user_message)
