# Tool-call UI: invocation animation and result display

**Date:** 2026-07-05
**Status:** Approved design
**Slice:** Surface tool invocations (currently the `recall` memory tool) in the chat UI —
a Claude-Code-style collapsible chip that animates while the tool runs and shows its
arguments and result on expansion. Vertical slice touching backend (SSE + persistence)
and frontend.

## Problem

The chat agent already carries one tool — `recall` (long-term memory search, wired in
`ChatService.stream_turn` via `make_recall_tool`). It runs **silently**: `BaseAgent.
stream_reply` streams only text deltas (`run_stream().stream_text()`), and the SSE
protocol only knows `delta` / `done` / `title` / `error`. The user never sees that a tool
was called or what it returned.

Goal: show, like Claude Code, that a tool was invoked (animated while running) and its
result (collapsible), both live during streaming and restored from history after reload.

## Decisions (locked)

- **Persistence:** tool calls are **saved in chat history** and restored when the chat is
  reopened (not live-only). Requires a schema change + migration.
- **UI fidelity:** **collapsed chip with expand** — icon + localized label, spinner while
  running, checkmark when done; click reveals arguments (`query`) and result. Closest to
  Claude Code.

## SSE protocol extension

Two new frames are added; existing `delta` / `done` / `title` / `error` frames are
unchanged.

```
event: tool-call
data: {"id": "<tool_call_id>", "name": "recall", "args": {"query": "..."}}

event: tool-result
data: {"id": "<tool_call_id>", "result": "- [work] ..."}
```

`id` is the pydantic-ai `tool_call_id`; it ties a result to its call. Emission order in a
turn: `tool-call` → `tool-result` → `delta`… (recall completes before the answer text).
Multiple tool calls in one turn are supported by matching on `id`.

## Backend

### Observing tool events

Rewrite `BaseAgent.stream_reply` from `agent.run_stream().stream_text()` to `agent.iter()`
node iteration (pydantic-ai 2.5, confirmed available):

- **model-request node** (`Agent.is_model_request_node`): stream text deltas as today
  (`TextPartDelta`), accumulate into `acc.text`.
- **call-tools node** (`Agent.is_call_tools_node`): observe `FunctionToolCallEvent`
  (`.part.tool_name`, `.part.args`, `.part.tool_call_id`) and `FunctionToolResultEvent`
  (`.part.content`, `.tool_call_id`).

`stream_reply` stops yielding bare `str`. It yields an **agent-level union** so the agent
layer stays free of `services` types:

```python
@dataclass
class StreamedText:      text: str
@dataclass
class StreamedToolCall:  id: str; name: str; args: dict[str, Any]
@dataclass
class StreamedToolResult: id: str; result: str
AgentStreamEvent = StreamedText | StreamedToolCall | StreamedToolResult
```

`args` is normalized to a dict (pydantic-ai `ToolCallPart.args` may be a JSON string —
parse it; fall back to `{}` on unparseable input). `result` is the tool return content
coerced to `str`. A `RetryPromptPart` result (tool error) is surfaced as its text.

### Service layer

- `events.py` gains `ToolCall(id, name, args)` and `ToolResult(id, result)` dataclasses;
  `StreamEvent = Delta | Done | ToolCall | ToolResult`.
- `ChatService.stream_turn` maps `StreamedText → Delta`, `StreamedToolCall → ToolCall`,
  `StreamedToolResult → ToolResult`, yielding them in order. It accumulates each completed
  call into `ReplyAccumulator.tool_calls: list[dict]` (`{id, name, args, result}`) for
  persistence.
- Routers (`send_message`, `regenerate_message`) gain two `isinstance` branches emitting
  the `tool-call` / `tool-result` SSE frames via the existing `_sse` helper.

### Persistence

- New column **`messages.tool_calls JSONB NULL`** — array of `{id, name, args, result}`.
- Alembic migration adding the nullable column (no backfill; existing rows stay `NULL`).
- `_persist_assistant` writes `acc.tool_calls` (or `NULL` when empty) onto the assistant
  row alongside `acc.text`.
- `MessageOut` schema gains `tool_calls: list[ToolCallOut] | None`.
- **`to_model_messages` is unchanged** — tool calls are display-only metadata and are not
  replayed into the model's context. The tool result already shaped the persisted answer
  text; reconstructing call/return pairs into model history is out of scope.

**Known limitation:** an assistant row is only written when there is text (`_persist_
assistant` returns `None` on empty `acc.text`, unchanged). For `recall`, answer text always
follows the tool call, so tool calls are not lost. A hypothetical tool-only turn with no
text would not persist its tool calls; acceptable for this slice.

## Frontend

- `ChatMessage` (in `useChatStream.ts`) gains `toolCalls?: ToolCallState[]` where
  `ToolCallState = { id: string; name: string; args: Record<string, unknown>; result?:
  string; running: boolean }`.
- `useChatStream.streamAssistant`:
  - `tool-call` → append a `ToolCallState` with `running: true`.
  - `tool-result` → patch the entry with matching `id`: set `result`, `running: false`.
  - abort/error → settle any still-running tool calls (`running: false`), mirroring text.
  - `loadHistory` maps each message's `tool_calls` into `toolCalls` (all `running: false`).
- `convertMessage.ts`: build assistant `content` as tool-call parts **before** the text
  part: `{ type: 'tool-call', toolCallId, toolName, args, result }`. Running state derives
  from `result === undefined` (assistant-ui renders in-progress tool parts without a
  result).
- New component **`ToolCallCard.tsx`** + `ToolCallCard.module.css`, wired via
  `MessagePrimitive.Content components={{ tools: { Fallback: ToolCallCard } }}` in
  `Thread.tsx`. Collapsed chip: icon + localized label, spinner while running → checkmark
  when done. Click toggles an expanded panel showing `query` (args) and the result text.
  Styled with the existing liquid-glass palette (reuse tokens from `Thread.module.css` /
  `tokens.css`).
- Localized tool-label map: `recall → «Поиск в памяти»`; unknown tool names fall back to
  the raw `toolName`.

## Error handling

- Tool error (`RetryPromptPart` result) is delivered as the `result` string and rendered in
  the card (styled as an error state). `recall` catches internally so this is rare.
- Stream abort mid-tool-call gates the spinner off (`running: false`) exactly as it settles
  the streaming text message.
- SSE `error` frame handling is unchanged.

## Testing (TDD — tests first)

**Backend:**
- `FunctionModel` scripted to call `recall` then answer: assert `ChatService.stream_turn`
  yields `ToolCall` → `ToolResult` → `Delta` → `Done` in order.
- Persistence: after a turn with a tool call, the assistant `messages` row has `tool_calls`
  populated with `{id, name, args, result}`.
- Router SSE test: response contains `event: tool-call` and `event: tool-result` frames
  with the expected JSON.
- `args`-normalization unit test: JSON-string args parsed to dict; unparseable → `{}`.

**Frontend:**
- `useChatStream`: feed an SSE sequence with `tool-call` + `tool-result` frames; assert the
  message's `toolCalls` transitions `running: true → false` with the result set.
- `ToolCallCard`: renders label + spinner while running; checkmark when done; click expands
  to show query + result; collapses again.
- `convertMessage`: produces tool-call parts before the text part; running part has no
  `result`.
- History load: a `getChat` response with `tool_calls` restores `toolCalls` on the message.

## Out of scope

- Feeding tool call/return pairs back into model history (`to_model_messages` unchanged).
- Persisting tool calls for text-less turns.
- Any tool beyond `recall` (design generalizes by `name`, but only `recall` exists).
- Streaming partial tool-argument deltas (args arrive complete on the `tool-call` frame).
