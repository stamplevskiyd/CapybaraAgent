"""Tests for agent-level tool-call and result streaming via agent.iter()."""

from pydantic_ai import Tool

from capybara.agent.base import (
    ReplyAccumulator,
    StreamedText,
    StreamedToolCall,
    StreamedToolResult,
)
from capybara.config import Settings
from support import ToolCallingFakeAgent


async def test_stream_reply_surfaces_tool_call_and_result(settings: Settings) -> None:
    """A registered tool produces a tool-call event, a result event, and text."""
    agent = ToolCallingFakeAgent(settings, "Готово")

    async def lookup(query: str) -> str:
        """Return a fixed answer for the given query."""
        return "сорок два"

    acc = ReplyAccumulator()
    events = [
        e async for e in agent.stream_reply("test-model", "сколько?", [], acc, tools=[Tool(lookup)])
    ]

    calls = [e for e in events if isinstance(e, StreamedToolCall)]
    results = [e for e in events if isinstance(e, StreamedToolResult)]
    texts = [e for e in events if isinstance(e, StreamedText)]

    assert len(calls) == 1
    assert calls[0].name == "lookup"
    assert isinstance(calls[0].args, dict)
    assert len(results) == 1
    assert results[0].id == calls[0].id  # result matches its call
    assert "сорок два" in results[0].result
    assert "".join(t.text for t in texts) == "Готово"

    # Accumulator records the completed call for persistence.
    assert acc.tool_calls == [
        {
            "id": calls[0].id,
            "name": "lookup",
            "args": calls[0].args,
            "result": results[0].result,
        }
    ]
    assert acc.text == "Готово"
