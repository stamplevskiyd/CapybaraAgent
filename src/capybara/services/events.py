"""SSE event dataclasses for the chat streaming protocol."""

from dataclasses import dataclass
from typing import Any


@dataclass
class Delta:
    """A streaming text delta chunk from the LLM."""

    text: str


@dataclass
class Done:
    """Final event indicating the assistant message was saved successfully."""

    message_id: str | None
    usage: dict[str, Any] | None


@dataclass
class ToolCall:
    """A tool invocation observed mid-turn, surfaced to the UI before its result."""

    id: str
    name: str
    args: dict[str, Any]


@dataclass
class ToolResult:
    """The result of a tool call, matched to it by ``id``."""

    id: str
    result: str


# Stream failures are surfaced by the router as an ``event: error`` SSE frame from its
# exception handler, not as a StreamEvent — the service raises rather than yielding.
StreamEvent = Delta | Done | ToolCall | ToolResult
