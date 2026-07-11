# Dual Agent Mode (Fast / Smart) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-thread agent mode toggle (Fast / Smart) so weak local models can use a simple `create_react_agent` loop instead of the DeepAgents runtime.

**Architecture:** Fast is a second LangGraph graph factory (`create_react_agent`) behind the existing `DeepAgentRunner`/checkpointer/tool-provider seams; mode is resolved per turn (message metadata → `chat_prefs.mode` → default `"fast"`) exactly like the model, and rides the same frontend plumbing.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2.0 async, Alembic, langgraph (`create_react_agent`), deepagents, Chainlit; React/TS + vitest frontend.

## Global Constraints

- Fast run recursion cap: `recursion_limit = 6` (run-config key, applied by the runner for Fast only). Smart uses LangGraph's default.
- Mode values: `Literal["fast", "smart"]`; default `"fast"` everywhere.
- ruff + mypy strict must stay clean (`uv run ruff check .`, `uv run mypy src`).
- Backend tests need Docker (testcontainers). Frontend tests need node ≥ 20 (`~/.nvm/versions/node/v22.23.1`).
- Docstrings mandatory on every module/class/function in `src` (ruff `D`, google; tests exempt).
- After editing backend code in the running container, `docker compose restart api` (uvicorn --reload does not see bind-mount changes on macOS).

---

### Task 1: Persist `mode` on chat_prefs (model, migration, schema, command)

**Files:**
- Modify: `src/capybara/db/models/chat_pref.py`
- Create: `src/capybara/migrations/versions/20260711_1600_b2c0cafe000b_chat_pref_mode.py`
- Modify: `src/capybara/api/schemas.py` (ChatPrefUpsert, ChatPrefOut)
- Modify: `src/capybara/commands/chat_pref/upsert.py`
- Test: `tests/test_migrations.py`, `tests/test_chat_pref_commands.py`

**Interfaces:**
- Produces: `ChatPref.mode: Mapped[str]` (default `"fast"`); `ChatPrefUpsert.mode` / `ChatPrefOut.mode: Literal["fast","smart"] = "fast"`; `UpsertChatPref(..., mode: str)`.

- [ ] **Step 1: Add the column to the model**

In `src/capybara/db/models/chat_pref.py`, add a CHECK constraint and column:

```python
from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint, Uuid
```

```python
    __table_args__ = (
        UniqueConstraint("user_id", "thread_id", name="user_id_thread_id"),
        CheckConstraint("mode IN ('fast', 'smart')", name="mode"),
    )
```

Add after the `model` column:

```python
    #: Agent runtime for this thread: 'fast' (simple react loop) or 'smart' (DeepAgents).
    mode: Mapped[str] = mapped_column(String(8), default="fast", nullable=False)
```

- [ ] **Step 2: Write the migration**

Create `src/capybara/migrations/versions/20260711_1600_b2c0cafe000b_chat_pref_mode.py`:

```python
"""add chat_prefs.mode (fast/smart agent mode)

Revision ID: b2c0cafe000b
Revises: a1c0ffee0001
Create Date: 2026-07-11 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c0cafe000b"
down_revision: str | Sequence[str] | None = "a1c0ffee0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the mode column (default 'fast') and its CHECK constraint."""
    op.add_column(
        "chat_prefs",
        sa.Column("mode", sa.String(length=8), nullable=False, server_default="fast"),
    )
    op.create_check_constraint(
        "ck_chat_prefs_mode", "chat_prefs", "mode IN ('fast', 'smart')"
    )


def downgrade() -> None:
    """Drop the mode column and its constraint."""
    op.drop_constraint("ck_chat_prefs_mode", "chat_prefs", type_="check")
    op.drop_column("chat_prefs", "mode")
```

- [ ] **Step 3: Write the failing migration test**

In `tests/test_migrations.py`, add:

```python
async def test_chat_prefs_has_mode_column(migrated_engine: AsyncEngine) -> None:
    """chat_prefs.mode exists after migrations, constrained to fast/smart."""
    async with migrated_engine.connect() as conn:
        cols = (
            (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'chat_prefs'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert "mode" in set(cols)
        checks = (
            (
                await conn.execute(
                    text(
                        "SELECT constraint_name FROM information_schema.check_constraints "
                        "WHERE constraint_name = 'ck_chat_prefs_mode'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert "ck_chat_prefs_mode" in set(checks)
```

- [ ] **Step 4: Run it to verify it fails**

Run: `uv run pytest tests/test_migrations.py::test_chat_prefs_has_mode_column -v`
Expected: FAIL (column `mode` missing — migration not yet picked up / assertion fails).

- [ ] **Step 5: Run it to verify it passes**

Run: `uv run pytest tests/test_migrations.py::test_chat_prefs_has_mode_column -v`
Expected: PASS (the migration from Step 2 adds the column).

- [ ] **Step 6: Add `mode` to the schemas**

In `src/capybara/api/schemas.py`, extend both chat-pref schemas. Add a module-level alias near `FactCategory`:

```python
AgentMode = Literal["fast", "smart"]
```

`ChatPrefOut`:

```python
class ChatPrefOut(BaseModel):
    """Response schema for a thread's per-user preferences."""

    model_config = ConfigDict(from_attributes=True)

    thread_id: UUID
    is_favorite: bool
    model: str | None
    mode: AgentMode
```

`ChatPrefUpsert`:

```python
class ChatPrefUpsert(BaseModel):
    """Request schema to set a thread's favorite flag, selected model, and agent mode."""

    is_favorite: bool = False
    model: str | None = Field(default=None, max_length=200)
    mode: AgentMode = "fast"
```

- [ ] **Step 7: Thread `mode` through the upsert command**

In `src/capybara/commands/chat_pref/upsert.py`, add `mode` to `__init__` and both write paths:

```python
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        user_id: UUID,
        thread_id: UUID,
        is_favorite: bool,
        model: str | None,
        mode: str,
    ) -> None:
        """Store the sessionmaker, the (user, thread) key, and the new field values."""
        self._sessionmaker = sessionmaker
        self._user_id = user_id
        self._thread_id = thread_id
        self._is_favorite = is_favorite
        self._model = model
        self._mode = mode
```

In `run()`, pass `mode=self._mode` to both `repo.create(...)` and `repo.update(...)`:

```python
            if pref is None:
                pref = await repo.create(
                    user_id=self._user_id,
                    thread_id=self._thread_id,
                    is_favorite=self._is_favorite,
                    model=self._model,
                    mode=self._mode,
                )
            else:
                pref = await repo.update(
                    pref, is_favorite=self._is_favorite, model=self._model, mode=self._mode
                )
```

- [ ] **Step 8: Write the failing command test**

In `tests/test_chat_pref_commands.py`, add (uses the existing `_maker` helper):

```python
async def test_upsert_persists_mode(
    session: AsyncSession,
    make_user,  # type: ignore[no-untyped-def]
) -> None:
    """UpsertChatPref writes the agent mode and updates it in place."""
    user = await make_user(session)
    await session.commit()
    maker = _maker(session)
    thread_id = uuid4()

    created = await UpsertChatPref(
        maker, user_id=user.id, thread_id=thread_id, is_favorite=False, model=None, mode="smart"
    ).execute()
    assert created.mode == "smart"

    updated = await UpsertChatPref(
        maker, user_id=user.id, thread_id=thread_id, is_favorite=False, model=None, mode="fast"
    ).execute()
    assert updated.id == created.id and updated.mode == "fast"
```

Update the existing calls in that file (`test_upsert_creates_then_updates_a_pref`, `test_prefs_are_scoped_to_the_owner`, `test_delete_removes_a_pref`) to pass `mode="fast"` in each `UpsertChatPref(...)` call.

- [ ] **Step 9: Run the chat-pref command tests**

Run: `uv run pytest tests/test_chat_pref_commands.py -v`
Expected: PASS (all, including the new mode test).

- [ ] **Step 10: Gates + commit**

```bash
uv run ruff check . && uv run mypy src
git add src/capybara/db/models/chat_pref.py src/capybara/migrations/versions/20260711_1600_b2c0cafe000b_chat_pref_mode.py src/capybara/api/schemas.py src/capybara/commands/chat_pref/upsert.py tests/test_migrations.py tests/test_chat_pref_commands.py
git commit -m "feat(chat-prefs): persist per-thread agent mode (fast/smart)"
```

---

### Task 2: Fast graph factory + runner mode argument

**Files:**
- Modify: `src/capybara/agent/deep_runtime.py` (GraphFactory type, `build_fast_graph`, `DeepAgentRunner.stream`)
- Modify: `src/capybara/app.py` (factory closure switches on mode)
- Test: `tests/test_deep_runtime.py`

**Interfaces:**
- Consumes: `ModelRegistry`, `build_graph` (existing).
- Produces: `build_fast_graph(registry, tools=None, *, model, checkpointer=None) -> EventStreamingGraph`; `FAST_RECURSION_LIMIT = 6`; `GraphFactory = Callable[[Sequence[ToolLike], str, str], EventStreamingGraph]`; `DeepAgentRunner.stream(content, *, model, thread_id, mode)`.

- [ ] **Step 1: Write the failing test for `build_fast_graph`**

In `tests/test_deep_runtime.py`, add (mirrors the existing `build_graph` test):

```python
async def test_build_fast_graph_wires_react_agent(
    settings, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """build_fast_graph hands the model, tools, and checkpointer to create_react_agent."""
    from capybara.agent import deep_runtime
    from capybara.agent.model_registry import ModelRegistry

    captured: dict[str, object] = {}

    def fake_create_react_agent(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return FakeGraph()

    monkeypatch.setattr(deep_runtime, "create_react_agent", fake_create_react_agent)
    sentinel_tool = object()
    sentinel_ckpt = object()

    deep_runtime.build_fast_graph(
        ModelRegistry(settings),
        [sentinel_tool],  # type: ignore[list-item]
        model="qwen2.5:latest",
        checkpointer=sentinel_ckpt,  # type: ignore[arg-type]
    )

    assert captured["model"].model == "qwen2.5:latest"  # type: ignore[union-attr]
    assert captured["tools"] == [sentinel_tool]
    assert captured["checkpointer"] is sentinel_ckpt
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_deep_runtime.py::test_build_fast_graph_wires_react_agent -v`
Expected: FAIL (`build_fast_graph` / `create_react_agent` attribute not defined).

- [ ] **Step 3: Implement `build_fast_graph` + import**

In `src/capybara/agent/deep_runtime.py`, add the import and constant near the top:

```python
from deepagents import create_deep_agent
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.prebuilt import create_react_agent
```

```python
#: Recursion cap for the Fast (react) loop — keeps a confused weak model from spinning.
FAST_RECURSION_LIMIT = 6

#: System prompt for the Fast react loop.
FAST_SYSTEM_PROMPT = (
    "You are CapybaraAgent, a local-first assistant. Answer directly and concisely. "
    "Use a tool only when it is clearly needed."
)
```

Add the factory next to `build_graph`:

```python
def build_fast_graph(
    registry: ModelRegistry,
    tools: Sequence[ToolLike] | None = None,
    *,
    model: str,
    checkpointer: BaseCheckpointSaver[str] | None = None,
) -> EventStreamingGraph:
    """Build the simple react-loop graph for Fast mode.

    A ``create_react_agent`` graph: one model+tools loop, no planning or subagents, for
    weak local models. Same LangGraph event stream and checkpointer contract as the Smart
    graph, so the runner and UI need no changes.
    """
    graph = create_react_agent(
        model=registry.chat_model(model),
        tools=list(tools or []),
        prompt=FAST_SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )
    return cast(EventStreamingGraph, graph)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/test_deep_runtime.py::test_build_fast_graph_wires_react_agent -v`
Expected: PASS.

- [ ] **Step 5: Write the failing test for runner passing mode + recursion config**

In `tests/test_deep_runtime.py`, replace the body of `test_runner_builds_graph_per_turn_with_provided_tools` (which currently asserts `calls == [([sentinel_tool], "llama3.1")]`) so the factory takes three args and the runner passes mode:

```python
async def test_runner_builds_graph_per_turn_with_tools_and_mode() -> None:
    """Each turn rebuilds the graph from that turn's tools, model, AND mode."""
    sentinel_tool = object()
    calls: list[tuple[list[ToolLike], str, str]] = []

    class FakeProvider:
        async def tools(self) -> Sequence[ToolLike]:
            return [sentinel_tool]  # type: ignore[list-item]

    def factory(tools: Sequence[ToolLike], model: str, mode: str) -> FakeGraph:
        calls.append((list(tools), model, mode))
        return FakeGraph()

    runner = DeepAgentRunner(factory, tool_provider=FakeProvider())
    events = [
        event
        async for event in runner.stream("Hi", model="llama3.1", thread_id="t1", mode="fast")
    ]

    assert calls == [([sentinel_tool], "llama3.1", "fast")]
    assert events == [RunnerEvent(kind="text", content="hello", name=None, payload=None)]
```

Also update the other `runner.stream(...)` calls in this file (`test_runner_streams_text_events`, `test_runner_normalizes_tool_start_and_end_events`, `test_runner_factory_without_provider_builds_toolless_graph`) to pass `mode="fast"`, and change their factory/`graph=` lambdas to accept `(tools, model, mode)` where they define a factory.

- [ ] **Step 6: Run it to verify it fails**

Run: `uv run pytest tests/test_deep_runtime.py -v`
Expected: FAIL (`stream()` has no `mode` param / factory called with 2 args).

- [ ] **Step 7: Update the runner and GraphFactory type**

In `src/capybara/agent/deep_runtime.py`, change the factory type and `stream`:

```python
#: Build a graph for one turn from that turn's tools, selected model, and mode.
GraphFactory = Callable[[Sequence["ToolLike"], str, str], EventStreamingGraph]
```

```python
    async def stream(
        self,
        content: str,
        *,
        model: str,
        thread_id: str,
        mode: str,
    ) -> AsyncIterator[RunnerEvent]:
        """Stream normalized text/tool events for one user message."""
        tools: Sequence[ToolLike] = []
        if self._tool_provider is not None:
            tools = await self._tool_provider.tools()
        graph = self._graph_factory(tools, model, mode)
        payload: dict[str, object] = {"messages": [{"role": "user", "content": content}]}
        config: dict[str, object] = {"configurable": {"thread_id": thread_id}}
        if mode == "fast":
            config["recursion_limit"] = FAST_RECURSION_LIMIT
        async for event in graph.astream_events(payload, version="v2", config=config):
            normalized = self._normalize_event(event)
            if normalized is not None:
                yield normalized
```

- [ ] **Step 8: Run it to verify it passes**

Run: `uv run pytest tests/test_deep_runtime.py -v`
Expected: PASS.

- [ ] **Step 9: Switch the app factory on mode**

In `src/capybara/app.py`, import `build_fast_graph` and make the factory mode-aware:

```python
from capybara.agent.deep_runtime import DeepAgentRunner, McpServerSpec, build_fast_graph, build_graph
```

```python
    def graph_factory(tools, model, mode):  # type: ignore[no-untyped-def]
        build = build_fast_graph if mode == "fast" else build_graph
        return build(model_registry, tools, model=model, checkpointer=checkpointer)

    app.state.deep_agent_runner = DeepAgentRunner(graph_factory, tool_provider=tool_provider)
```

- [ ] **Step 10: Gates + commit**

```bash
uv run ruff check . && uv run mypy src
git add src/capybara/agent/deep_runtime.py src/capybara/app.py tests/test_deep_runtime.py
git commit -m "feat(agent): add Fast react-loop graph and per-turn mode selection"
```

---

### Task 3: Resolve mode in the Chainlit runtime

**Files:**
- Modify: `src/capybara/chainlit_app.py` (`selected_mode`, `on_message`)
- Test: `tests/test_chainlit_model_selection.py` (add a mode-resolution class)

**Interfaces:**
- Consumes: `_pref_lookup` (returns a `ChatPref` with `.mode`), `current_user_id`, `_default_model`.
- Produces: `selected_mode(metadata, thread_id) -> str` (default `"fast"`); `on_message` passes `mode=` to `stream_agent_message` → `runner.stream`.

- [ ] **Step 1: Write the failing test**

In `tests/test_chainlit_model_selection.py`, the `FakePref` currently only has `model`. Add `mode` to it and add resolution tests:

```python
class FakePref:
    def __init__(self, model: str | None, mode: str = "fast") -> None:
        self.model = model
        self.mode = mode
```

```python
async def test_mode_from_metadata_wins(configured) -> None:  # type: ignore[no-untyped-def]
    configured(FakePrefLookup(FakePref(None, mode="fast")))
    assert await chainlit_app.selected_mode({"mode": "smart"}, str(uuid4())) == "smart"


async def test_mode_from_pref_when_no_metadata(configured) -> None:  # type: ignore[no-untyped-def]
    configured(FakePrefLookup(FakePref(None, mode="smart")))
    assert await chainlit_app.selected_mode(None, str(uuid4())) == "smart"


async def test_mode_defaults_to_fast(configured) -> None:  # type: ignore[no-untyped-def]
    configured(FakePrefLookup(None))
    assert await chainlit_app.selected_mode(None, str(uuid4())) == "fast"


async def test_mode_ignores_invalid_metadata_value(configured) -> None:  # type: ignore[no-untyped-def]
    configured(FakePrefLookup(None))
    assert await chainlit_app.selected_mode({"mode": "bogus"}, str(uuid4())) == "fast"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_chainlit_model_selection.py -k mode -v`
Expected: FAIL (`selected_mode` not defined).

- [ ] **Step 3: Implement `selected_mode`**

In `src/capybara/chainlit_app.py`, add after `selected_model`:

```python
#: Valid agent modes; anything else resolves to the default.
_AGENT_MODES = ("fast", "smart")


async def selected_mode(metadata: dict[str, object] | None, thread_id: str) -> str:
    """Resolve the agent mode for one turn.

    Precedence mirrors ``selected_model``: the mode sent with this message, then the
    thread's saved pref, then the default ``"fast"``. An unknown value resolves to the
    default rather than raising.
    """
    candidate = (metadata or {}).get("mode")
    if isinstance(candidate, str) and candidate in _AGENT_MODES:
        return candidate
    user_id = current_user_id()
    if _pref_lookup is not None and user_id is not None:
        try:
            pref = await _pref_lookup(user_id, UUID(thread_id))
        except ValueError:
            pref = None
        if pref is not None and pref.mode in _AGENT_MODES:
            return pref.mode
    return "fast"
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/test_chainlit_model_selection.py -k mode -v`
Expected: PASS.

- [ ] **Step 5: Thread mode through `on_message` and `stream_agent_message`**

In `src/capybara/chainlit_app.py`, `stream_agent_message` currently calls
`runner.stream(content, model=model, thread_id=thread_id)`. Add a `mode` parameter to the
helper and pass it through:

```python
async def stream_agent_message(
    *,
    runner: DeepAgentRunner,
    content: str,
    model: str,
    mode: str,
    thread_id: str,
    response: cl.Message,
    new_step: Callable[[str], cl.Step] = _tool_step,
) -> None:
```

```python
    async for event in runner.stream(content, model=model, thread_id=thread_id, mode=mode):
```

In `on_message`, resolve the mode and pass it:

```python
    thread_id = cl.context.session.thread_id
    model = await selected_model(message.metadata, thread_id)
    mode = await selected_mode(message.metadata, thread_id)
    try:
        await stream_agent_message(
            runner=_runtime_runner,
            content=message.content,
            model=model,
            mode=mode,
            thread_id=thread_id,
            response=cl.Message(content=""),
        )
```

- [ ] **Step 6: Fix the flow test**

`tests/test_chainlit_deepagents_flow.py` calls `stream_agent_message(...)` and its
`FakeRunner.stream` has signature `(content, *, model, thread_id)`. Add `mode` to both:
the fake's `stream` signature gains `mode: str`, and each `stream_agent_message(...)` call
passes `mode="fast"`.

- [ ] **Step 7: Run the chainlit tests**

Run: `uv run pytest tests/test_chainlit_model_selection.py tests/test_chainlit_deepagents_flow.py -v`
Expected: PASS.

- [ ] **Step 8: Gates + commit**

```bash
uv run ruff check . && uv run mypy src
git add src/capybara/chainlit_app.py tests/test_chainlit_model_selection.py tests/test_chainlit_deepagents_flow.py
git commit -m "feat(chainlit): resolve per-turn agent mode alongside the model"
```

- [ ] **Step 9: Full backend suite + live restart**

```bash
uv run pytest -q
docker compose restart api
```
Expected: all tests pass; api restarts clean (`docker compose logs api --since 1m | grep "Application startup complete"`).

---

### Task 4: Frontend types, chat-prefs, thread merge

**Files:**
- Modify: `frontend/src/api/types.ts` (ChatOut, ChatPrefOut)
- Modify: `frontend/src/chat/chatPrefs.ts` (putChatPref carries mode)
- Modify: `frontend/src/chat/useThreads.ts` (merge mode)
- Modify: `frontend/src/chat/messages.ts` (AgentMode type)
- Test: `frontend/src/chat/useThreads.test.tsx` (create if absent — see note)

**Interfaces:**
- Produces: `type AgentMode = 'fast' | 'smart'`; `ChatOut.mode: AgentMode`; `ChatPrefOut.mode: AgentMode`; `putChatPref(api, threadId, { is_favorite, model, mode })`.

- [ ] **Step 1: Add the AgentMode type**

In `frontend/src/chat/messages.ts`, add:

```typescript
export type AgentMode = 'fast' | 'smart'
```

- [ ] **Step 2: Extend the TS API types**

In `frontend/src/api/types.ts`, import-free literal is fine; add `mode` to both:

```typescript
import type { AgentMode } from '../chat/messages'
```

```typescript
export interface ChatOut {
  id: string
  title: string
  model: string | null
  is_favorite: boolean
  mode: AgentMode
  created_at: string
  updated_at: string
}
```

```typescript
export interface ChatPrefOut {
  thread_id: string
  is_favorite: boolean
  model: string | null
  mode: AgentMode
}
```

- [ ] **Step 3: Carry mode in putChatPref**

In `frontend/src/chat/chatPrefs.ts`:

```typescript
import type { AgentMode, ChatPrefOut } from '../api/types'

export const putChatPref = (
  api: ApiClient,
  threadId: string,
  pref: { is_favorite: boolean; model: string | null; mode: AgentMode },
) => api.put<ChatPrefOut>(`/chat-prefs/${threadId}`, pref)
```

(Keep `listChatPrefs` / `deleteChatPref` unchanged. `AgentMode` is re-exported from `api/types` via the import in Step 2, so importing it from `../api/types` here works; if lint prefers, import from `../chat/messages`.)

- [ ] **Step 4: Merge mode in useThreads**

In `frontend/src/chat/useThreads.ts`, in the `.map` that builds each `ChatOut`, add:

```typescript
          return {
            id: thread.id,
            title: thread.name ?? 'Новый чат',
            model: pref?.model ?? null,
            is_favorite: pref?.is_favorite ?? false,
            mode: pref?.mode ?? 'fast',
            created_at: createdAt,
            updated_at: createdAt,
          }
```

- [ ] **Step 5: Write the failing test**

In `frontend/src/chat/useThreads.test.tsx` (create if it does not exist):

```tsx
import { renderHook, waitFor } from '@testing-library/react'
import { server, http, HttpResponse } from '../test/msw'
import { AuthProvider } from '../auth/AuthContext'
import { useThreads } from './useThreads'

vi.mock('../chainlit/client', () => ({
  chainlitClient: {
    listThreads: async () => ({
      pageInfo: { hasNextPage: false, startCursor: null, endCursor: null },
      data: [{ id: 't1', name: 'Чат', createdAt: '2026-07-11T00:00:00Z', steps: [] }],
    }),
  },
}))

const wrapper = ({ children }: { children: React.ReactNode }) => <AuthProvider>{children}</AuthProvider>

beforeEach(() =>
  localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'r' })),
)

test('merges the mode from chat-prefs into the thread entry', async () => {
  server.use(
    http.get('/api/chat-prefs', () =>
      HttpResponse.json([{ thread_id: 't1', is_favorite: false, model: 'qwen2.5', mode: 'smart' }]),
    ),
  )
  const { result } = renderHook(() => useThreads(), { wrapper })
  await waitFor(() => expect(result.current.chats.length).toBe(1))
  expect(result.current.chats[0].mode).toBe('smart')
})

test('defaults mode to fast when no pref exists', async () => {
  const { result } = renderHook(() => useThreads(), { wrapper })
  await waitFor(() => expect(result.current.chats.length).toBe(1))
  expect(result.current.chats[0].mode).toBe('fast')
})
```

- [ ] **Step 6: Run frontend tests**

Run: `cd frontend && npx vitest run src/chat/useThreads.test.tsx`
(Ensure `PATH` has node ≥ 20: `export PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH"`.)
Expected: PASS.

- [ ] **Step 7: Typecheck + commit**

```bash
export PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH"
cd frontend && npx tsc --noEmit && npm run lint
cd .. && git add frontend/src/api/types.ts frontend/src/chat/chatPrefs.ts frontend/src/chat/useThreads.ts frontend/src/chat/messages.ts frontend/src/chat/useThreads.test.tsx
git commit -m "feat(frontend): carry per-thread agent mode through chat-prefs"
```

---

### Task 5: Composer mode toggle + ChatScreen plumbing

**Files:**
- Modify: `frontend/src/components/Composer.tsx` (mode select)
- Modify: `frontend/src/chainlit/useChainlitThread.ts` (send rides mode)
- Modify: `frontend/src/screens/ChatScreen.tsx` (agentMode state, persist, pass to composer)
- Modify: `frontend/src/chat/lastModel.ts` → add mode persistence helpers (or inline)
- Test: `frontend/src/screens/ChatScreen.test.tsx`, `frontend/src/components/Composer.test.tsx`

**Interfaces:**
- Consumes: `AgentMode`, `putChatPref`, `useThreads`.
- Produces: `Composer` props `selectedMode: AgentMode`, `onSelectMode: (m: AgentMode) => void`; `useChainlitThread().send(content, model, mode)`.

- [ ] **Step 1: Send rides mode in metadata**

In `frontend/src/chainlit/useChainlitThread.ts`, extend `send`:

```typescript
import type { AgentMode } from '../chat/messages'
```

```typescript
  const send = useCallback(
    async (content: string, model?: string | null, mode?: AgentMode) => {
      sendMessage({
        name: 'user',
        type: 'user_message',
        output: content,
        // The backend reads the turn's model AND mode from here.
        metadata: { ...(model ? { model } : {}), ...(mode ? { mode } : {}) },
      })
    },
    [sendMessage],
  )
```

- [ ] **Step 2: Add the mode selector to the Composer**

In `frontend/src/components/Composer.tsx`, add two props and a native `<select>` next to the model one:

```typescript
import type { AgentMode } from '../chat/messages'
```

```typescript
export function Composer({
  models,
  selectedModel,
  onSelectModel,
  selectedMode,
  onSelectMode,
}: {
  models: string[]
  selectedModel: string | null
  onSelectModel: (m: string) => void
  selectedMode: AgentMode
  onSelectMode: (m: AgentMode) => void
}) {
```

After the model `<select>` (inside the same `.row`), add:

```tsx
        <select
          className={styles.modelSelect}
          aria-label="Режим агента"
          value={selectedMode}
          onChange={(e) => onSelectMode(e.target.value as AgentMode)}
        >
          <option value="fast">Быстрый</option>
          <option value="smart">Умный</option>
        </select>
```

- [ ] **Step 3: Write the failing Composer test**

In `frontend/src/components/Composer.test.tsx`, add (follow the file's existing render harness — it renders inside an `AssistantRuntimeProvider`; copy the existing setup and add the two new props `selectedMode="fast"` and an `onSelectMode` spy):

```tsx
test('renders the agent-mode selector and reports a change', async () => {
  const onSelectMode = vi.fn()
  renderComposer({ selectedMode: 'fast', onSelectMode }) // use this file's existing render helper
  const select = screen.getByLabelText('Режим агента')
  expect(select).toHaveValue('fast')
  await userEvent.selectOptions(select, 'smart')
  expect(onSelectMode).toHaveBeenCalledWith('smart')
})
```

If `Composer.test.tsx` has no reusable render helper, replicate the existing test's render block and pass all props including `models`, `selectedModel`, `onSelectModel`, `selectedMode`, `onSelectMode`.

- [ ] **Step 4: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/components/Composer.test.tsx`
Expected: FAIL (label "Режим агента" not found).

- [ ] **Step 5: ChatScreen: mode state, persistence, wiring**

In `frontend/src/screens/ChatScreen.tsx`:

Add state near `draftModel` (persist to localStorage under `capybara.lastMode`):

```typescript
  const [draftMode, setDraftMode] = useState<AgentMode>(() => {
    const v = localStorage.getItem('capybara.lastMode')
    return v === 'smart' ? 'smart' : 'fast'
  })
```

Add the import:

```typescript
import type { AgentMode } from '../chat/messages'
```

Derive the active mode (mirror `selectedModel`):

```typescript
  const selectedMode = activeChat?.mode ?? draftMode
```

`handleSend` passes mode:

```typescript
    await send(text, selectedModel, selectedMode)
```

`handleSelectModel`'s `putChatPref` call gains `mode`:

```typescript
        await putChatPref(api, activeThreadId, { is_favorite: wasFavorite, model, mode: selectedMode })
```

Add a mode handler:

```typescript
  async function handleSelectMode(mode: AgentMode) {
    localStorage.setItem('capybara.lastMode', mode)
    setDraftMode(mode)
    if (activeThreadId) {
      patchLocal(activeThreadId, { mode })
      try {
        await putChatPref(api, activeThreadId, {
          is_favorite: activeChat?.is_favorite ?? false,
          model: activeChat?.model ?? draftModel,
          mode,
        })
      } catch {
        await reload()
      }
    }
  }
```

`handleToggleFavorite`'s `putChatPref` call gains `mode: chat?.mode ?? 'fast'`. The adoption effect's `putChatPref` gains `mode: draftMode`.

Pass the new props to BOTH `<Composer>` instances (welcome + active):

```tsx
                <Composer
                  models={models}
                  selectedModel={selectedModel}
                  onSelectModel={handleSelectModel}
                  selectedMode={selectedMode}
                  onSelectMode={handleSelectMode}
                />
```

- [ ] **Step 6: Update the ChatScreen mock + add a persistence test**

`ChatScreen.test.tsx` mocks `useChainlitThread`; its fake `send` records `{ content, model }`. Extend the fake to record `mode` (`send: async (content, model, mode) => { sent.calls.push({ content, model, mode }) ... }`) and update the existing `sent.calls` assertion in "welcome greets…" to `{ content: 'Привет', model: 'llama3.1:8b', mode: 'fast' }`. The `MemoryNav.test.tsx` mock's `send` signature also gains `mode` (no assertion needed there).

Add a mode-persistence test (mirrors the existing model-persistence test):

```tsx
test('selecting a mode on an active thread persists it to chat-prefs', async () => {
  let putBody: unknown = null
  server.use(
    http.get('/api/models', () =>
      HttpResponse.json({ provider: 'ollama', models: ['llama3.1:8b'] }),
    ),
    http.post('/chainlit/project/threads', () =>
      HttpResponse.json({
        pageInfo: { hasNextPage: false, startCursor: null, endCursor: null },
        data: [thread],
      }),
    ),
    http.put('/api/chat-prefs/c1', async ({ request }) => {
      putBody = await request.json()
      return HttpResponse.json({ thread_id: 'c1', is_favorite: false, model: null, mode: 'smart' })
    }),
  )
  render(
    <AuthProvider>
      <ChatScreen />
    </AuthProvider>,
  )
  await userEvent.click(await screen.findByText('Мой чат'))
  await userEvent.selectOptions(await screen.findByLabelText('Режим агента'), 'smart')
  await waitFor(() =>
    expect(putBody).toMatchObject({ mode: 'smart' }),
  )
})
```

Note: the `thread` fixture in this file needs no `mode` (it is a Chainlit thread, not a pref); the pref merge defaults it to `fast`.

- [ ] **Step 7: Run frontend tests**

Run: `cd frontend && npx vitest run`
Expected: PASS (all files).

- [ ] **Step 8: Typecheck, lint, build, commit**

```bash
export PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH"
cd frontend && npx tsc --noEmit && npm run lint && npm run build
cd .. && git add frontend/src
git commit -m "feat(frontend): agent-mode toggle in the composer, persisted per thread"
```

- [ ] **Step 9: Live smoke**

```bash
docker compose restart api
```
In the browser (hard-reload): pick **Быстрый**, send a simple message with a weak local model → it answers without a recursion error; ask a follow-up referencing the first message → dialog memory works. Switch a thread to **Умный** → DeepAgents runtime runs. Reload the page → the thread keeps its mode.

---

## Notes for the implementer

- The `ChatOut` frontend type gains a required `mode`; any test fixture building a `ChatOut`-shaped object (e.g. in `ChatScreen.test.tsx`) that TypeScript checks may need `mode: 'fast'`. The sidebar `thread` fixtures are Chainlit threads (not `ChatOut`) and are unaffected; `useThreads` synthesizes `mode`.
- Do not add tool-menu UI (Python/web/SQL/shell) — out of scope for this slice.
- `create_react_agent` and `create_deep_agent` both accept `checkpointer=`; the shared `InMemorySaver` is passed by the app factory for both modes.
