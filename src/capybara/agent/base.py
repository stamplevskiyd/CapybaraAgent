"""Abstract base agent, error types, and reply accumulator for LLM streaming."""

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import Agent, Tool
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
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


class EmbeddingDimensionError(Exception):
    """Raised when the provider returns embeddings of an unexpected dimensionality.

    Distinct from a provider outage: Ollama answered, but the vectors do not match the
    dimensionality the ``facts.embedding`` column expects (usually because a different
    embedding model was configured). Caught early so the failure is an actionable config
    error, not a late 500 on the DB write.
    """

    def __init__(self, expected: int, actual: int, model_name: str) -> None:
        """Record the expected vs actual dimensions and the embedding model in use."""
        self.expected = expected
        self.actual = actual
        self.model_name = model_name
        super().__init__(
            f"Embedding model {model_name!r} returned {actual}-dim vectors, "
            f"but {expected} dimensions are expected. Check the configured embedding model."
        )


@dataclass
class StreamedText:
    """A streamed text delta from the model."""

    text: str


@dataclass
class StreamedToolCall:
    """A tool invocation observed mid-run, before its result is known."""

    id: str
    name: str
    args: dict[str, Any]


@dataclass
class StreamedToolResult:
    """The result of a previously streamed tool call, matched by ``id``."""

    id: str
    result: str


#: What ``BaseAgent.stream_reply`` yields: interleaved text and tool events.
AgentStreamEvent = StreamedText | StreamedToolCall | StreamedToolResult


def _coerce_tool_args(args: object) -> dict[str, Any]:
    """Normalise pydantic-ai tool-call args (dict or JSON string) to a dict.

    Returns an empty dict for anything that is not a dict and does not parse as a
    JSON object, so the UI always receives a well-formed args object.
    """
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except ValueError, TypeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _text_of(event: object) -> str:
    """Extract streamed text from a model-request-node event, or '' if none.

    Handles both the initial ``PartStartEvent`` for a ``TextPart`` and subsequent
    ``PartDeltaEvent`` ``TextPartDelta`` updates; non-text parts (e.g. tool calls) yield ''.
    """
    if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
        return event.part.content
    if isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
        return event.delta.content_delta
    return ""


def _coerce_tool_result(part: object) -> str:
    """Render a tool return/retry part's content as a string for the UI."""
    content = getattr(part, "content", "")
    return content if isinstance(content, str) else str(content)


@dataclass
class ReplyAccumulator:
    """Accumulate streaming text, usage stats, model name, and tool calls from a run."""

    text: str = ""
    usage: dict[str, Any] | None = None
    model: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


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
    ) -> AsyncIterator[AgentStreamEvent]:
        """Stream text and tool events for the named model, accumulating into acc.

        Uses ``agent.iter()`` so tool calls and their results are observable and can be
        surfaced to the UI. Text deltas fill ``acc.text``; each completed tool call is
        appended to ``acc.tool_calls`` as ``{"id", "name", "args", "result"}`` for
        persistence. When *tools* are supplied the chat system prompt (recall nudge) is
        set; with no tools the prompt is left empty so behaviour is unchanged.
        """
        tool_list = list(tools)
        agent: Agent[None, str] = Agent(
            self._build_model(model_name),
            system_prompt=CHAT_SYSTEM_PROMPT if tool_list else (),
            tools=tool_list,
        )
        # tool_call_id → index into acc.tool_calls, so a result can patch its call.
        pending: dict[str, int] = {}
        async with agent.iter(user_content, message_history=history) as run:
            async for node in run:
                if Agent.is_model_request_node(node):
                    async with node.stream(run.ctx) as request_stream:
                        async for text_event in request_stream:
                            text = _text_of(text_event)
                            if text:
                                acc.text += text
                                yield StreamedText(text=text)
                elif Agent.is_call_tools_node(node):
                    async with node.stream(run.ctx) as tool_stream:
                        async for tool_event in tool_stream:
                            if isinstance(tool_event, FunctionToolCallEvent):
                                args = _coerce_tool_args(tool_event.part.args)
                                pending[tool_event.part.tool_call_id] = len(acc.tool_calls)
                                acc.tool_calls.append(
                                    {
                                        "id": tool_event.part.tool_call_id,
                                        "name": tool_event.part.tool_name,
                                        "args": args,
                                        "result": None,
                                    }
                                )
                                yield StreamedToolCall(
                                    id=tool_event.part.tool_call_id,
                                    name=tool_event.part.tool_name,
                                    args=args,
                                )
                            elif isinstance(tool_event, FunctionToolResultEvent):
                                result = _coerce_tool_result(tool_event.part)
                                idx = pending.get(tool_event.tool_call_id)
                                if idx is not None:
                                    acc.tool_calls[idx]["result"] = result
                                yield StreamedToolResult(id=tool_event.tool_call_id, result=result)
        final = run.result
        if final is not None:
            run_usage = final.usage
            acc.usage = {"total_tokens": run_usage.total_tokens} if run_usage.has_values() else None
            acc.model = final.response.model_name

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
