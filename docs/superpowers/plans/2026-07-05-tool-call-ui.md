# Tool-call UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the `recall` memory tool's invocation and result in the chat UI as a Claude-Code-style collapsible chip — animated while running, expandable to show arguments and result — live during streaming and restored from history.

**Architecture:** The agent layer rewrites `stream_reply` to observe tool events via `agent.iter()` and yields a small event union. `ChatService` maps that union to service `Delta`/`ToolCall`/`ToolResult` events and accumulates tool calls for persistence in a new `messages.tool_calls` JSONB column. Two new SSE frames (`tool-call`, `tool-result`) carry the events to the frontend, where `useChatStream` tracks per-message tool-call state, `convertMessage` emits assistant-ui tool-call parts, and a new `ToolCallCard` component renders the chip.

**Tech Stack:** Python 3.12+, pydantic-ai 2.5, FastAPI SSE, SQLAlchemy 2.0 async, Alembic, pytest + testcontainers; React + TypeScript, assistant-ui 0.14, Vitest + Testing Library + MSW.

## Global Constraints

- Python fully type-annotated; strict mypy; ruff lint + format; every module/class/function has a docstring (google convention, pydocstyle `select = D`); tests exempt from docstrings.
- Layering: `api → services → repositories → db`; no DB access in routers/services outside repositories; agent layer must not import from `services`.
- TDD: write the failing test first, watch it fail, implement minimally, watch it pass, commit.
- Backend tests run against real Postgres via testcontainers with per-test isolation; use pydantic-ai `TestModel`/`FunctionModel` — never a real LLM.
- Frontend copy is Russian (e.g. tool label «Поиск в памяти»); match the existing liquid-glass palette via CSS-module tokens.
- Commit after each task. Stage only the files listed in the task — never `git add -A` (the user commits concurrently).
- Run backend gates before committing a backend task: `uv run ruff format . && uv run ruff check . && uv run mypy src && uv run pytest`. Run frontend gates before committing a frontend task: `cd frontend && npm run lint && npx tsc --noEmit && npm test`.

---

## File Structure

**Backend (create/modify):**
- `src/capybara/agent/base.py` — add streamed-event union + `_coerce_tool_args`; add `ReplyAccumulator.tool_calls`; rewrite `stream_reply` on `agent.iter()`.
- `src/capybara/services/events.py` — add `ToolCall`, `ToolResult`; extend `StreamEvent`.
- `src/capybara/services/chat_service.py` — map agent events → service events, accumulate tool calls, persist them.
- `src/capybara/db/models/message.py` — add `tool_calls` JSONB column.
- `src/capybara/migrations/versions/20260705_1200_e5d0cafe0005_message_tool_calls.py` — new migration.
- `src/capybara/api/schemas.py` — `ToolCallOut` + `MessageOut.tool_calls`.
- `src/capybara/api/routers/chats.py` — emit `tool-call`/`tool-result` SSE frames in both stream endpoints.
- `tests/support.py` — update fake agents to the new yield type; add `ScriptedToolAgent`.
- `tests/test_agent_stream.py`, `tests/test_agent_tool_stream.py` (new), `tests/test_chat_service.py`, `tests/test_chats_api.py`, `tests/test_migrations.py` — tests.

**Frontend (create/modify):**
- `frontend/src/chat/useChatStream.ts` — `ToolCallState`, event handling, history mapping.
- `frontend/src/api/types.ts` — `ToolCallOut` + `MessageOut.tool_calls`.
- `frontend/src/chat/convertMessage.ts` — emit tool-call parts.
- `frontend/src/components/ToolCallCard.tsx` + `ToolCallCard.module.css` — the chip (new).
- `frontend/src/components/Thread.tsx` — wire `tools.Fallback`.
- Tests: `frontend/src/chat/useChatStream.test.tsx`, `frontend/src/chat/convertMessage.test.ts`, `frontend/src/components/ToolCallCard.test.tsx` (new).

---

## Task 1: Agent-level tool-event streaming

Rewrite `stream_reply` to observe tool calls/results via `agent.iter()` and yield a typed event union instead of bare strings. Update `ReplyAccumulator` and the fake agents/tests that depend on the old string-yield contract.

**Files:**
- Modify: `src/capybara/agent/base.py`
- Modify: `tests/support.py`
- Modify: `tests/test_agent_stream.py`
- Test: `tests/test_agent_tool_stream.py` (create)

**Interfaces:**
- Produces:
  - `StreamedText(text: str)`, `StreamedToolCall(id: str, name: str, args: dict[str, Any])`, `StreamedToolResult(id: str, result: str)` dataclasses; `AgentStreamEvent = StreamedText | StreamedToolCall | StreamedToolResult`.
  - `ReplyAccumulator.tool_calls: list[dict[str, Any]]` (each `{"id", "name", "args", "result"}`).
  - `BaseAgent.stream_reply(...) -> AsyncIterator[AgentStreamEvent]` (signature otherwise unchanged).

- [ ] **Step 1: Write the failing agent-level tool-stream test**

Create `tests/test_agent_tool_stream.py`:

```python
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
        e
        async for e in agent.stream_reply(
            "test-model", "сколько?", [], acc, tools=[Tool(lookup)]
        )
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_agent_tool_stream.py -v`
Expected: FAIL with `ImportError` (`StreamedText` etc. not defined).

- [ ] **Step 3: Add the event union, `_coerce_tool_args`, and `tool_calls` to the accumulator**

In `src/capybara/agent/base.py`, extend the imports from `pydantic_ai.messages`:

```python
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
    ToolReturnPart,
    UserPromptPart,
)
```

Add `import json` at the top (with the stdlib imports) and add these dataclasses just above `ReplyAccumulator`:

```python
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
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}
```

Add the `tool_calls` field to `ReplyAccumulator`:

```python
@dataclass
class ReplyAccumulator:
    """Accumulate streaming text, usage stats, model name, and tool calls from a run."""

    text: str = ""
    usage: dict[str, Any] | None = None
    model: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
```

Add `field` to the `dataclasses` import: `from dataclasses import dataclass, field`.

- [ ] **Step 4: Rewrite `stream_reply` on `agent.iter()`**

Replace the body of `stream_reply` in `src/capybara/agent/base.py` with:

```python
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
                        async for event in request_stream:
                            text = _text_of(event)
                            if text:
                                acc.text += text
                                yield StreamedText(text=text)
                elif Agent.is_call_tools_node(node):
                    async with node.stream(run.ctx) as tool_stream:
                        async for event in tool_stream:
                            if isinstance(event, FunctionToolCallEvent):
                                args = _coerce_tool_args(event.part.args)
                                pending[event.part.tool_call_id] = len(acc.tool_calls)
                                acc.tool_calls.append(
                                    {
                                        "id": event.part.tool_call_id,
                                        "name": event.part.tool_name,
                                        "args": args,
                                        "result": None,
                                    }
                                )
                                yield StreamedToolCall(
                                    id=event.part.tool_call_id,
                                    name=event.part.tool_name,
                                    args=args,
                                )
                            elif isinstance(event, FunctionToolResultEvent):
                                result = _coerce_tool_result(event.part)
                                idx = pending.get(event.tool_call_id)
                                if idx is not None:
                                    acc.tool_calls[idx]["result"] = result
                                yield StreamedToolResult(
                                    id=event.tool_call_id, result=result
                                )
        final = run.result
        if final is not None:
            run_usage = final.usage()
            acc.usage = (
                {"total_tokens": run_usage.total_tokens} if run_usage.has_values() else None
            )
            acc.model = final.response.model_name
```

Add these two module-level helpers near `_coerce_tool_args`:

```python
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
```

Note: leave `to_model_messages` and `generate_title` unchanged.

- [ ] **Step 5: Run the new test to verify it passes**

Run: `uv run pytest tests/test_agent_tool_stream.py -v`
Expected: PASS.

- [ ] **Step 6: Update the fake agents and the existing agent-stream test to the union**

In `tests/support.py`, update the two overriding fakes so their `stream_reply` yields the union. Add the import `from capybara.agent.base import BaseAgent, ReplyAccumulator, StreamedText`.

`RaisingAgent.stream_reply` — change the return annotation and the trailing sentinel:

```python
    ) -> AsyncIterator[StreamedText]:
        """Raise immediately; the trailing yield only marks this as a generator."""
        raise RuntimeError(self._message)
        yield StreamedText(text="")  # pragma: no cover
```

`PartialThenFailAgent.stream_reply` — yield a `StreamedText`:

```python
    ) -> AsyncIterator[StreamedText]:
        """Yield one accumulated delta, then raise to abort the stream."""
        acc.text += self._partial
        yield StreamedText(text=self._partial)
        raise RuntimeError(self._message)
```

In `tests/test_agent_stream.py`, rewrite `test_stream_reply_yields_deltas_and_fills_accumulator` to consume the union:

```python
from capybara.agent.base import BaseAgent, ReplyAccumulator, StreamedText


async def test_stream_reply_yields_deltas_and_fills_accumulator(
    settings: Settings,
) -> None:
    agent = FakeAgent(settings, "Привет, Роман")
    acc = ReplyAccumulator()
    events = [e async for e in agent.stream_reply("test-model", "Привет", [], acc)]
    text = "".join(e.text for e in events if isinstance(e, StreamedText))
    assert text == "Привет, Роман"
    assert acc.text == "Привет, Роман"
    assert acc.model == "test"
    assert acc.usage is not None and acc.usage["total_tokens"] > 0
    assert acc.tool_calls == []
```

- [ ] **Step 7: Run the full agent + support test suite**

Run: `uv run pytest tests/test_agent_stream.py tests/test_agent_tool_stream.py -v`
Expected: PASS.

- [ ] **Step 8: Gates + commit**

Run: `uv run ruff format . && uv run ruff check . && uv run mypy src && uv run pytest tests/test_agent_stream.py tests/test_agent_tool_stream.py tests/test_memory_recall_tool.py`
Expected: all PASS.

```bash
git add src/capybara/agent/base.py tests/support.py tests/test_agent_stream.py tests/test_agent_tool_stream.py
git commit -m "feat(agent): surface tool calls/results as streamed events via agent.iter"
```

---

## Task 2: Service-layer tool events

Add `ToolCall`/`ToolResult` service events and map the agent event union to them in `ChatService.stream_turn`, accumulating tool calls for persistence.

**Files:**
- Modify: `src/capybara/services/events.py`
- Modify: `src/capybara/services/chat_service.py`
- Test: `tests/test_chat_service.py`

**Interfaces:**
- Consumes: `StreamedText`, `StreamedToolCall`, `StreamedToolResult`, `ReplyAccumulator.tool_calls` (Task 1).
- Produces:
  - `ToolCall(id: str, name: str, args: dict[str, Any])`, `ToolResult(id: str, result: str)`; `StreamEvent = Delta | Done | ToolCall | ToolResult`.
  - `ChatService.stream_turn` now yields `ToolCall`/`ToolResult` interleaved before `Delta`s; `_persist_assistant` stores `acc.tool_calls`.

- [ ] **Step 1: Write the failing service test with a scripted tool agent**

Add a `ScriptedToolAgent` to `tests/support.py` (append at end) that yields a fixed event sequence and fills the accumulator, so the service/router can be tested without model-driven tool calls:

```python
class ScriptedToolAgent(FakeAgent):
    """Agent whose stream yields a fixed tool-call → tool-result → text sequence.

    Lets service and router tests exercise tool-event mapping and persistence
    deterministically, independent of TestModel's tool-calling behaviour.
    """

    async def stream_reply(  # type: ignore[override]
        self,
        model_name: str,
        user_content: str,
        history,  # type: ignore[no-untyped-def]
        acc: ReplyAccumulator,
        tools=(),  # type: ignore[no-untyped-def]
    ):
        """Yield one tool call, its result, then the configured text."""
        from capybara.agent.base import StreamedToolCall, StreamedToolResult

        args = {"query": "любимое"}
        acc.tool_calls.append(
            {"id": "call-1", "name": "recall", "args": args, "result": None}
        )
        yield StreamedToolCall(id="call-1", name="recall", args=args)
        acc.tool_calls[0]["result"] = "- [personal] походы"
        yield StreamedToolResult(id="call-1", result="- [personal] походы")
        acc.text += self._output_text
        yield StreamedText(text=self._output_text)
        acc.model = "test"
```

Make sure `tests/support.py` imports `StreamedText` (added in Task 1). In `tests/test_chat_service.py`, add:

```python
from capybara.services.events import Delta, Done, ToolCall, ToolResult
from support import ScriptedToolAgent


async def test_stream_turn_emits_and_persists_tool_calls(
    engine: AsyncEngine,
    settings: Settings,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """Tool call/result events are streamed in order and stored on the assistant row."""
    user_id, chat_id = await _seed_chat(engine, make_user, "tool_user")
    maker = create_sessionmaker(engine)

    service = ChatService(maker, ScriptedToolAgent(settings, "Ответ"))

    model, history = await service.begin_turn(user_id, chat_id, "Что я люблю?")  # type: ignore[arg-type]
    events = [
        e
        async for e in service.stream_turn(
            chat_id, model, "Что я люблю?", history, user_id=user_id
        )
    ]

    kinds = [type(e).__name__ for e in events]
    assert kinds.index("ToolCall") < kinds.index("ToolResult") < kinds.index("Delta")
    call = next(e for e in events if isinstance(e, ToolCall))
    res = next(e for e in events if isinstance(e, ToolResult))
    assert call.name == "recall" and call.args == {"query": "любимое"}
    assert res.id == call.id and "походы" in res.result
    assert any(isinstance(e, Done) for e in events)

    async with maker() as check:
        stored = await MessageRepo(check).list(FieldEquals(Message.chat_id, chat_id))
    assistant = stored[-1]
    assert assistant.role == "assistant"
    assert assistant.tool_calls == [
        {"id": "call-1", "name": "recall", "args": {"query": "любимое"}, "result": "- [personal] походы"}
    ]
```

(`assistant.tool_calls` depends on the column added in Task 3; this test will fully pass after Task 3. Verify the event-ordering assertions pass now and re-run after Task 3 for persistence.)

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_chat_service.py::test_stream_turn_emits_and_persists_tool_calls -v`
Expected: FAIL with `ImportError` (`ToolCall` not defined).

- [ ] **Step 3: Add the service events**

In `src/capybara/services/events.py`, add after `Done`:

```python
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
```

and widen the union:

```python
StreamEvent = Delta | Done | ToolCall | ToolResult
```

- [ ] **Step 4: Map the agent union in `stream_turn` and persist tool calls**

In `src/capybara/services/chat_service.py`:
- Update the import: `from capybara.services.events import Delta, Done, StreamEvent, ToolCall, ToolResult`.
- Add: `from capybara.agent.base import StreamedText, StreamedToolCall, StreamedToolResult` (alongside the existing `from capybara.agent.base import BaseAgent, ReplyAccumulator`).

Replace the streaming loop in `stream_turn`:

```python
        try:
            async for event in self._agent.stream_reply(
                model_name, user_content, history, acc, tools=tools
            ):
                if isinstance(event, StreamedText):
                    yield Delta(text=event.text)
                elif isinstance(event, StreamedToolCall):
                    yield ToolCall(id=event.id, name=event.name, args=event.args)
                elif isinstance(event, StreamedToolResult):
                    yield ToolResult(id=event.id, result=event.result)
            completed = True
        finally:
            assistant_id = await self._persist_assistant(chat_id, acc, completed=completed)
        if completed:
            yield Done(message_id=assistant_id, usage=acc.usage)
```

In `_persist_assistant`, pass the tool calls to the repo `create` (the column and repo arg land in Task 3). For now add the keyword so the shape is ready:

```python
            assistant = await messages.create(
                chat_id=chat_id,
                role="assistant",
                content=acc.text,
                model=acc.model,
                usage_json=acc.usage,
                incomplete=not completed,
                tool_calls=acc.tool_calls or None,
            )
```

- [ ] **Step 5: Run the event-ordering assertions**

Run: `uv run pytest tests/test_chat_service.py -v`
Expected: the new test may still FAIL on the `tool_calls` persistence assertion and on `messages.create(tool_calls=...)` until Task 3. Confirm the pre-existing chat-service tests still PASS (they use `FakeAgent`, which emits no tool events). If `messages.create` rejects the `tool_calls` kwarg, proceed to Task 3 before re-running — do not commit yet.

- [ ] **Step 6: Commit (with Task 3) — see Task 3 Step 7**

This task's code is committed together with Task 3, since `_persist_assistant` depends on the new column and repo argument. Do not commit in isolation.

---

## Task 3: Persist tool calls (schema, migration, repo, API schema)

Add the `messages.tool_calls` JSONB column, a migration, the `MessageRepo.create` argument, and the `MessageOut.tool_calls` response field. This completes Task 2's persistence path.

**Files:**
- Modify: `src/capybara/db/models/message.py`
- Modify: `src/capybara/repositories/message_repo.py`
- Create: `src/capybara/migrations/versions/20260705_1200_e5d0cafe0005_message_tool_calls.py`
- Modify: `src/capybara/api/schemas.py`
- Test: `tests/test_chat_service.py` (re-run Task 2 test), `tests/test_migrations.py`

**Interfaces:**
- Consumes: `acc.tool_calls` and `messages.create(tool_calls=...)` (Task 2).
- Produces:
  - `Message.tool_calls: list[dict[str, Any]] | None` ORM column.
  - `MessageRepo.create(..., tool_calls: list[dict[str, Any]] | None = None)`.
  - `ToolCallOut` Pydantic model and `MessageOut.tool_calls: list[ToolCallOut] | None`.

- [ ] **Step 1: Write the failing migration/column test**

In `tests/test_migrations.py`, add:

```python
from sqlalchemy import inspect


async def test_messages_has_tool_calls_column(migrated_engine: AsyncEngine) -> None:
    """The tool_calls JSONB column exists after migrations run."""

    def _columns(sync_conn):  # type: ignore[no-untyped-def]
        return {c["name"] for c in inspect(sync_conn).get_columns("messages")}

    async with migrated_engine.connect() as conn:
        cols = await conn.run_sync(_columns)
    assert "tool_calls" in cols
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_migrations.py::test_messages_has_tool_calls_column -v`
Expected: FAIL (`tool_calls` not in columns).

- [ ] **Step 3: Add the ORM column**

In `src/capybara/db/models/message.py`, add after `usage_json`:

```python
    #: Display-only record of tool invocations in this assistant turn: a list of
    #: ``{"id", "name", "args", "result"}``. ``NULL`` when the turn used no tools.
    #: Not replayed into model context — see ``to_model_messages``.
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
```

(`Any` and `JSONB` are already imported in this module.)

- [ ] **Step 4: Add the repo argument**

In `src/capybara/repositories/message_repo.py`, add a `tool_calls` parameter to `create` and pass it to the `Message(...)` constructor. Locate the existing `create` signature and extend it — keep the existing parameters and their order, appending:

```python
        tool_calls: list[dict[str, Any]] | None = None,
```

and include `tool_calls=tool_calls` in the `Message(...)` instantiation. Ensure `Any` is imported (`from typing import Any`) — add it if missing.

- [ ] **Step 5: Write the migration**

First confirm the current head:

Run: `uv run alembic heads`
Expected: shows `d4d0cafe0004` (the composite-indexes migration). If it differs, set `down_revision` below to the reported head.

Create `src/capybara/migrations/versions/20260705_1200_e5d0cafe0005_message_tool_calls.py`:

```python
"""add messages.tool_calls jsonb column

Revision ID: e5d0cafe0005
Revises: d4d0cafe0004
Create Date: 2026-07-05 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "e5d0cafe0005"
down_revision: str | Sequence[str] | None = "d4d0cafe0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable tool_calls JSONB column to messages."""
    op.add_column("messages", sa.Column("tool_calls", JSONB(), nullable=True))


def downgrade() -> None:
    """Drop the tool_calls column from messages."""
    op.drop_column("messages", "tool_calls")
```

- [ ] **Step 6: Add the API response schema**

In `src/capybara/api/schemas.py`, add above `MessageOut`:

```python
class ToolCallOut(BaseModel):
    """Response schema for a single tool invocation within an assistant message."""

    id: str
    name: str
    args: dict[str, Any]
    result: str | None
```

and add the field to `MessageOut`:

```python
    tool_calls: list[ToolCallOut] | None = None
```

Ensure `Any` is imported in `schemas.py` (`from typing import Any`) — add it if missing.

- [ ] **Step 7: Run the migration + service tests, then gates + commit (Tasks 2 & 3)**

Run: `uv run pytest tests/test_migrations.py tests/test_chat_service.py tests/test_memory_recall_tool.py -v`
Expected: PASS, including `test_stream_turn_emits_and_persists_tool_calls`.

Run gates: `uv run ruff format . && uv run ruff check . && uv run mypy src && uv run pytest`
Expected: all PASS.

```bash
git add src/capybara/services/events.py src/capybara/services/chat_service.py \
        src/capybara/db/models/message.py src/capybara/repositories/message_repo.py \
        src/capybara/api/schemas.py \
        src/capybara/migrations/versions/20260705_1200_e5d0cafe0005_message_tool_calls.py \
        tests/support.py tests/test_chat_service.py tests/test_migrations.py
git commit -m "feat(chat): tool-call service events and history persistence"
```

---

## Task 4: SSE frames for tool events

Emit `tool-call` and `tool-result` SSE frames from both stream endpoints.

**Files:**
- Modify: `src/capybara/api/routers/chats.py`
- Test: `tests/test_chats_api.py`

**Interfaces:**
- Consumes: `ToolCall`, `ToolResult` service events (Task 2).
- Produces: SSE frames `event: tool-call\ndata: {"id","name","args"}` and `event: tool-result\ndata: {"id","result"}`.

- [ ] **Step 1: Write the failing router SSE test**

First read `tests/test_chats_api.py::test_send_message_stream_error_is_generic` — it is the canonical example of overriding `get_agent` for a single test with `settings` and `app` in scope. Model the new test on its structure exactly, swapping the agent for `ScriptedToolAgent`. Add `ScriptedToolAgent` to the existing `from support import ...` line.

Concretely, the test builds its own client (mirroring how `test_send_message_stream_error_is_generic` sets up `app.dependency_overrides` and instantiates `AsyncClient`), overriding `get_agent` to `lambda: ScriptedToolAgent(settings, "Ответ")`. Then it drives one turn and asserts on the SSE body:

```python
    chat_id = (
        await ac.post("/chats", json={"title": "c", "model": "test-model"})
    ).json()["id"]
    async with ac.stream(
        "POST", f"/chats/{chat_id}/messages", json={"content": "Что?"}
    ) as resp:
        body = ""
        async for chunk in resp.aiter_text():
            body += chunk

    assert "event: tool-call" in body
    assert "event: tool-result" in body
    assert '"name": "recall"' in body
    assert "event: delta" in body
```

Use the same client variable name and setup/teardown (`app.dependency_overrides.clear()` in a `finally`) as the model test uses — do not invent a new fixture.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_chats_api.py::test_send_message_streams_tool_call_frames -v`
Expected: FAIL — `event: tool-call` not in body (router does not emit it yet).

- [ ] **Step 3: Emit the frames in both endpoints**

In `src/capybara/api/routers/chats.py`, update the import: `from capybara.services.events import Delta, Done, ToolCall, ToolResult`.

In `send_message`'s `event_stream`, add branches inside the `async for event` loop (after the `Delta` branch, before/after `Done`):

```python
                if isinstance(event, Delta):
                    yield _sse("delta", {"text": event.text})
                elif isinstance(event, ToolCall):
                    yield _sse("tool-call", {"id": event.id, "name": event.name, "args": event.args})
                elif isinstance(event, ToolResult):
                    yield _sse("tool-result", {"id": event.id, "result": event.result})
                elif isinstance(event, Done):
                    yield _sse("done", {"message_id": event.message_id, "usage": event.usage})
```

Apply the identical `ToolCall`/`ToolResult` branches to `regenerate_message`'s `event_stream` loop.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_chats_api.py -v`
Expected: PASS.

- [ ] **Step 5: Gates + commit**

Run: `uv run ruff format . && uv run ruff check . && uv run mypy src && uv run pytest`
Expected: all PASS.

```bash
git add src/capybara/api/routers/chats.py tests/test_chats_api.py
git commit -m "feat(api): emit tool-call and tool-result SSE frames"
```

---

## Task 5: Frontend chat store — tool-call state

Track per-message tool-call state from the new SSE frames and restore it from history.

**Files:**
- Modify: `frontend/src/chat/useChatStream.ts`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/chat/chatApi.ts` (only if it re-maps `MessageOut` → history; see Step 4)
- Test: `frontend/src/chat/useChatStream.test.tsx`

**Interfaces:**
- Consumes: SSE `tool-call` / `tool-result` frames (Task 4); `MessageOut.tool_calls` (Task 3).
- Produces:
  - `ToolCallState = { id: string; name: string; args: Record<string, unknown>; result?: string; running: boolean }`.
  - `ChatMessage.toolCalls?: ToolCallState[]`.

- [ ] **Step 1: Write the failing store test**

In `frontend/src/chat/useChatStream.test.tsx`, add:

```typescript
test('tracks tool-call state through running and result frames', async () => {
  server.use(
    http.post('/api/chats/c1/messages', () => {
      const body =
        'event: tool-call\ndata: {"id":"t1","name":"recall","args":{"query":"хобби"}}\n\n' +
        'event: tool-result\ndata: {"id":"t1","result":"- [personal] походы"}\n\n' +
        'event: delta\ndata: {"text":"Вы любите походы"}\n\n' +
        'event: done\ndata: {"message_id":"m1"}\n\n'
      return new HttpResponse(body, { headers: { 'Content-Type': 'text/event-stream' } })
    }),
  )
  const { result } = renderHook(() => useChatStream('c1'), { wrapper })
  await act(async () => {
    await result.current.send('Что я люблю?')
  })
  await waitFor(() => expect(result.current.sending).toBe(false))
  const assistant = result.current.messages.find((m) => m.role === 'assistant')!
  expect(assistant.toolCalls).toHaveLength(1)
  expect(assistant.toolCalls![0]).toMatchObject({
    id: 't1',
    name: 'recall',
    args: { query: 'хобби' },
    result: '- [personal] походы',
    running: false,
  })
  expect(assistant.content).toBe('Вы любите походы')
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npm test -- useChatStream`
Expected: FAIL (`assistant.toolCalls` is undefined).

- [ ] **Step 3: Add the type and event handling**

In `frontend/src/chat/useChatStream.ts`, add above `ChatMessage`:

```typescript
export type ToolCallState = {
  id: string
  name: string
  args: Record<string, unknown>
  result?: string
  running: boolean
}
```

Add the field to `ChatMessage`:

```typescript
  toolCalls?: ToolCallState[]
```

In `streamAssistant`, add two event branches inside the `for await (const ev of parseSse(...))` loop, alongside the existing `delta`/`done`/`error`/`title`:

```typescript
          } else if (ev.event === 'tool-call') {
            const tc = JSON.parse(ev.data) as { id: string; name: string; args: Record<string, unknown> }
            patch((m) => ({
              ...m,
              toolCalls: [...(m.toolCalls ?? []), { ...tc, running: true }],
            }))
          } else if (ev.event === 'tool-result') {
            const { id, result } = JSON.parse(ev.data) as { id: string; result: string }
            patch((m) => ({
              ...m,
              toolCalls: (m.toolCalls ?? []).map((t) =>
                t.id === id ? { ...t, result, running: false } : t,
              ),
            }))
```

Settle running tool calls when a stream aborts or errors. In the two abort/settle sites and the error branch of `streamAssistant`, extend the patch to also clear `running`. Add a helper near the top of `streamAssistant`:

```typescript
      const settleToolCalls = (m: ChatMessage): ChatMessage => ({
        ...m,
        toolCalls: m.toolCalls?.map((t) => (t.running ? { ...t, running: false } : t)),
      })
```

and apply it in each place the message is settled on abort — replace `patch((m) => ({ ...m, streaming: false }))` in the abort paths with `patch((m) => settleToolCalls({ ...m, streaming: false }))`, and in the catch-all error branch include `...settleToolCalls(m)` before overriding `streaming`/`error`.

- [ ] **Step 4: Map tool calls from history**

Locate where history is loaded into `ChatMessage`s. In `useChatStream.ts`, `loadHistory` maps `detail.messages`. Extend the mapping:

```typescript
        detail.messages.map((m) => ({
          id: m.id,
          role: m.role === 'user' ? 'user' : 'assistant',
          content: m.content,
          streaming: false,
          toolCalls: m.tool_calls
            ? m.tool_calls.map((t) => ({
                id: t.id,
                name: t.name,
                args: t.args,
                result: t.result ?? undefined,
                running: false,
              }))
            : undefined,
        })),
```

In `frontend/src/api/types.ts`, add the `ToolCallOut` interface and extend `MessageOut`:

```typescript
export interface ToolCallOut {
  id: string
  name: string
  args: Record<string, unknown>
  result: string | null
}
```

and inside `MessageOut` add:

```typescript
  tool_calls?: ToolCallOut[] | null
```

If `getChat` in `frontend/src/chat/chatApi.ts` maps `MessageOut` through an intermediate type, ensure `tool_calls` is carried through; if it returns the raw `ChatDetailOut`, no change is needed there.

- [ ] **Step 5: Run the store test to verify it passes**

Run: `cd frontend && npm test -- useChatStream`
Expected: PASS (including the pre-existing streaming/cancel tests).

- [ ] **Step 6: Gates + commit**

Run: `cd frontend && npm run lint && npx tsc --noEmit && npm test -- useChatStream`
Expected: PASS.

```bash
git add frontend/src/chat/useChatStream.ts frontend/src/api/types.ts frontend/src/chat/chatApi.ts
git commit -m "feat(chat-ui): track tool-call state from SSE and history"
```

(Drop `frontend/src/chat/chatApi.ts` from the `git add` if it was not modified.)

---

## Task 6: Convert tool calls to assistant-ui parts

Emit tool-call message parts (before the text part) from `convertMessage`.

**Files:**
- Modify: `frontend/src/chat/convertMessage.ts`
- Test: `frontend/src/chat/convertMessage.test.ts`

**Interfaces:**
- Consumes: `ChatMessage.toolCalls` (Task 5).
- Produces: assistant-ui `ThreadMessageLike.content` with `{ type: 'tool-call', toolCallId, toolName, args, result }` parts ahead of the text part.

- [ ] **Step 1: Write the failing converter test**

In `frontend/src/chat/convertMessage.test.ts`, add:

```typescript
test('emits tool-call parts before the text part', () => {
  const msg = convertMessage({
    id: 'a1',
    role: 'assistant',
    content: 'Ответ',
    streaming: false,
    toolCalls: [
      { id: 't1', name: 'recall', args: { query: 'х' }, result: 'r', running: false },
    ],
  })
  expect(msg.content).toHaveLength(2)
  expect(msg.content[0]).toMatchObject({
    type: 'tool-call',
    toolCallId: 't1',
    toolName: 'recall',
    args: { query: 'х' },
    result: 'r',
  })
  expect(msg.content[1]).toMatchObject({ type: 'text', text: 'Ответ' })
})

test('a running tool call has no result', () => {
  const msg = convertMessage({
    id: 'a2',
    role: 'assistant',
    content: '',
    streaming: true,
    toolCalls: [{ id: 't2', name: 'recall', args: {}, running: true }],
  })
  expect(msg.content[0]).toMatchObject({ type: 'tool-call', toolCallId: 't2' })
  expect((msg.content[0] as { result?: unknown }).result).toBeUndefined()
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npm test -- convertMessage`
Expected: FAIL (only the text part is present).

- [ ] **Step 3: Emit tool-call parts**

Rewrite `frontend/src/chat/convertMessage.ts`:

```typescript
/** Translate our ChatMessage into assistant-ui's parts-based ThreadMessageLike. */
import type { ThreadMessageLike } from '@assistant-ui/react'
import type { ChatMessage } from './useChatStream'

export function convertMessage(m: ChatMessage): ThreadMessageLike {
  const toolParts = (m.toolCalls ?? []).map((t) => ({
    type: 'tool-call' as const,
    toolCallId: t.id,
    toolName: t.name,
    args: t.args,
    ...(t.result !== undefined ? { result: t.result } : {}),
  }))
  const textParts = m.content ? [{ type: 'text' as const, text: m.content }] : []
  return {
    id: m.id,
    role: m.role,
    // Tool-call parts render before the answer text; empty text ⇒ no text part, so
    // assistant-ui reports hasContent=false and the typing indicator can show.
    content: [...toolParts, ...textParts],
    status: m.streaming ? { type: 'running' } : undefined,
  }
}
```

- [ ] **Step 4: Run the converter test to verify it passes**

Run: `cd frontend && npm test -- convertMessage`
Expected: PASS.

- [ ] **Step 5: Gates + commit**

Run: `cd frontend && npm run lint && npx tsc --noEmit && npm test -- convertMessage`
Expected: PASS.

```bash
git add frontend/src/chat/convertMessage.ts frontend/src/chat/convertMessage.test.ts
git commit -m "feat(chat-ui): render tool-call parts before assistant text"
```

---

## Task 7: ToolCallCard component and Thread wiring

Render the collapsible tool-call chip and wire it into the thread as the tool fallback component.

**Files:**
- Create: `frontend/src/components/ToolCallCard.tsx`
- Create: `frontend/src/components/ToolCallCard.module.css`
- Modify: `frontend/src/components/Thread.tsx`
- Test: `frontend/src/components/ToolCallCard.test.tsx` (create)

**Interfaces:**
- Consumes: assistant-ui `ToolCallMessagePartComponent` props (`toolName`, `args`, `result`, `status`).
- Produces: a `tools.Fallback` component wired into `MessagePrimitive.Content`.

- [ ] **Step 1: Write the failing component test**

Create `frontend/src/components/ToolCallCard.test.tsx`:

```typescript
import { render, screen, fireEvent } from '@testing-library/react'
import { ToolCallCard } from './ToolCallCard'

function renderCard(props: Partial<Parameters<typeof ToolCallCard>[0]> = {}) {
  const base = {
    toolName: 'recall',
    args: { query: 'хобби' },
    result: '- [personal] походы',
    status: { type: 'complete' as const },
  }
  // assistant-ui passes many props; the component only reads a subset.
  return render(<ToolCallCard {...(base as never)} {...(props as never)} />)
}

test('shows the localized label and expands to reveal args and result', () => {
  renderCard()
  expect(screen.getByText('Поиск в памяти')).toBeInTheDocument()
  // collapsed: result not shown yet
  expect(screen.queryByText(/походы/)).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button'))
  expect(screen.getByText(/походы/)).toBeInTheDocument()
  expect(screen.getByText(/хобби/)).toBeInTheDocument()
})

test('shows a running state while the tool executes', () => {
  renderCard({ result: undefined, status: { type: 'running' } as never })
  expect(screen.getByRole('status')).toBeInTheDocument()
})

test('falls back to the raw tool name for unknown tools', () => {
  renderCard({ toolName: 'weather' })
  expect(screen.getByText('weather')).toBeInTheDocument()
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npm test -- ToolCallCard`
Expected: FAIL (module `./ToolCallCard` not found).

- [ ] **Step 3: Create the CSS module**

Create `frontend/src/components/ToolCallCard.module.css` (mirror the liquid-glass palette used in `Thread.module.css`; adjust variable names to those actually defined in `tokens.css`):

```css
.card {
  margin: 4px 0;
  border: 1px solid var(--border, rgba(255, 255, 255, 0.12));
  border-radius: 10px;
  background: var(--surface-2, rgba(255, 255, 255, 0.04));
  overflow: hidden;
  font-size: 13px;
}

.header {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  background: none;
  border: none;
  color: inherit;
  cursor: pointer;
  text-align: left;
}

.header:hover {
  background: var(--surface-3, rgba(255, 255, 255, 0.06));
}

.label {
  flex: 1;
  font-weight: 500;
}

.spinner {
  width: 13px;
  height: 13px;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  opacity: 0.8;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.check {
  color: var(--success, #4ade80);
}

.chevron {
  transition: transform 0.15s ease;
}

.chevronOpen {
  transform: rotate(90deg);
}

.body {
  padding: 8px 10px;
  border-top: 1px solid var(--border, rgba(255, 255, 255, 0.12));
}

.field {
  margin: 4px 0;
}

.fieldLabel {
  opacity: 0.6;
  margin-right: 6px;
}

.value {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 12px;
}

.error {
  color: var(--danger, #f87171);
}
```

(If the repo's tokens define `--color-success` / `--color-border`, prefer those names over the generic ones above.)

- [ ] **Step 4: Create the component**

Create `frontend/src/components/ToolCallCard.tsx`:

```typescript
/**
 * Collapsible tool-call chip, Claude-Code style: icon + localized label with a spinner
 * while the tool runs and a checkmark when it completes. Clicking expands the arguments
 * and result. Rendered as the assistant-ui `tools.Fallback` component inside a message.
 */
import { useState } from 'react'
import type { ToolCallMessagePartComponent } from '@assistant-ui/react'
import { Brain, Check, ChevronRight } from 'lucide-react'
import styles from './ToolCallCard.module.css'

/** Human-readable, localized labels for known tools; unknown tools show their raw name. */
const TOOL_LABELS: Record<string, string> = {
  recall: 'Поиск в памяти',
}

/** Render the tool arguments as a compact single-line string. */
function formatArgs(args: unknown): string {
  if (args && typeof args === 'object') {
    const entries = Object.entries(args as Record<string, unknown>)
    if (entries.length === 1) return String(entries[0][1])
    return JSON.stringify(args)
  }
  return String(args ?? '')
}

export const ToolCallCard: ToolCallMessagePartComponent = ({ toolName, args, result, status }) => {
  const [open, setOpen] = useState(false)
  const running = status?.type === 'running' || status?.type === 'requires-action'
  const label = TOOL_LABELS[toolName] ?? toolName
  const resultText = result === undefined || result === null ? '' : String(result)

  return (
    <div className={styles.card}>
      <button
        type="button"
        className={styles.header}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <Brain size={15} />
        <span className={styles.label}>{label}</span>
        {running ? (
          <span className={styles.spinner} role="status" aria-label="Инструмент выполняется" />
        ) : (
          <Check size={15} className={styles.check} />
        )}
        <ChevronRight
          size={15}
          className={`${styles.chevron} ${open ? styles.chevronOpen : ''}`}
        />
      </button>
      {open && (
        <div className={styles.body}>
          <div className={styles.field}>
            <span className={styles.fieldLabel}>Запрос:</span>
            <span className={styles.value}>{formatArgs(args)}</span>
          </div>
          {!running && (
            <div className={styles.field}>
              <span className={styles.fieldLabel}>Результат:</span>
              <span className={styles.value}>{resultText}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 5: Run the component test to verify it passes**

Run: `cd frontend && npm test -- ToolCallCard`
Expected: PASS.

If a test fails because assistant-ui's `status` union member names differ (e.g. `'complete'` vs `'success'`), inspect `ToolCallMessagePartStatus` in `node_modules/@assistant-ui/react/dist/index.d.ts` and align the test's `status` literals and the component's `running` check to the real members. The `running` state maps to whichever status is emitted while a result is absent.

- [ ] **Step 6: Wire the component into the thread**

In `frontend/src/components/Thread.tsx`, import the card and pass it as the tools fallback. Change the assistant content line:

```typescript
import { ToolCallCard } from './ToolCallCard'
```

```typescript
        <MessagePrimitive.Content
          components={{ Text: MarkdownText, tools: { Fallback: ToolCallCard } }}
        />
```

- [ ] **Step 7: Full frontend gates + commit**

Run: `cd frontend && npm run lint && npx tsc --noEmit && npm test`
Expected: all PASS.

```bash
git add frontend/src/components/ToolCallCard.tsx frontend/src/components/ToolCallCard.module.css \
        frontend/src/components/ToolCallCard.test.tsx frontend/src/components/Thread.tsx
git commit -m "feat(chat-ui): collapsible tool-call chip with running/result states"
```

---

## Task 8: Full-stack verification

Confirm both suites are green and the feature works end-to-end.

**Files:** none (verification only).

- [ ] **Step 1: Backend gates**

Run: `uv run ruff format . && uv run ruff check . && uv run mypy src && uv run pytest`
Expected: all PASS.

- [ ] **Step 2: Frontend gates**

Run: `cd frontend && npm run lint && npx tsc --noEmit && npm test`
Expected: all PASS.

- [ ] **Step 3: Manual smoke (optional, needs Ollama + a tool-capable model)**

Run the app (`docker compose up --build` per CLAUDE.md), open a chat whose model supports tool calls, seed a memory fact, and ask a question that triggers `recall`. Confirm the chip appears with a spinner, resolves to a checkmark, and expands to show the query and result. Reload the chat and confirm the chip is restored from history.

- [ ] **Step 4: Confirm no stray changes**

Run: `git status`
Expected: only the files from Tasks 1–7 are committed; no unrelated files staged.

---

## Notes for the implementer

- **`stream_reply` is now the single tool-observation point.** Do not also try to parse tool calls in `ChatService` — it only maps the agent event union.
- **`to_model_messages` stays text-only.** Tool calls are display metadata; never feed them back into model history. Do not touch `test_begin_turn_excludes_incomplete_from_history`.
- **Empty-text turns still persist no row** (`_persist_assistant` returns `None` on empty `acc.text`). This is unchanged and acceptable — `recall` is always followed by answer text. A tool-only turn would drop its tool calls; out of scope.
- **assistant-ui status member names** (`running`/`complete`/etc.) are the one place the exact literals must be checked against the installed `@assistant-ui/react` types — do it in Task 7 Step 5 rather than trusting this plan's guesses.
- **CSS token names** in `ToolCallCard.module.css` must match those actually defined in `frontend/src/theme/tokens.css`; the fallbacks in the `var(...)` calls keep it working if a token is missing, but prefer the real names.
