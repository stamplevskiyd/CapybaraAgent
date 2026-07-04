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


# Stream failures are surfaced by the router as an ``event: error`` SSE frame from its
# exception handler, not as a StreamEvent — the service raises rather than yielding.
StreamEvent = Delta | Done
