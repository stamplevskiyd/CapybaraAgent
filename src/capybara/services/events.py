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

    message_id: str
    usage: dict[str, Any] | None


@dataclass
class Error:
    """Event indicating an error occurred during streaming."""

    message: str


StreamEvent = Delta | Done | Error
