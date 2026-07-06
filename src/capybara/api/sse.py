"""Shared Server-Sent-Events framing helpers for streaming endpoints."""

import json
from typing import Any

# Headers every SSE streaming response must carry so the Vite dev proxy, nginx, and the
# browser treat this as a live stream and never buffer chunks.
SSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def format_sse(event: str, data: dict[str, Any]) -> str:
    """Format one SSE frame as ``event: <name>`` / ``data: <json>``."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
