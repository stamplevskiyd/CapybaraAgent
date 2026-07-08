# Chainlit + DeepAgents Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate CapybaraAgent from a hand-rolled FastAPI/SSE/pydantic-ai chat runtime to a Chainlit + DeepAgents runtime while preserving the custom Capybara design, current features, and planned product surfaces.

**Architecture:** Use FastAPI as the outer ASGI shell and mount Chainlit at `/chainlit`, so existing custom REST surfaces for memory, MCP, models, profiles, and future tasks can coexist with Chainlit-managed chat sessions. Keep the React design shell, but replace the custom chat SSE/runtime adapter with a Chainlit React-client adapter. Replace the pydantic-ai agent layer with a DeepAgents runner that emits Chainlit messages/steps instead of manually parsing tool-call events.

**Tech Stack:** Python 3.12/3.13 compatibility target, FastAPI shell, Chainlit mounted app, DeepAgents/LangGraph/LangChain, Ollama via LangChain providers, PostgreSQL + SQLAlchemy for domain tables, Chainlit data layer for threads/steps, Vite + React + TypeScript custom UI.

---

## Scope Check

This is a broad platform migration. Do not implement it as one mega-commit.

The migration is split into shippable slices:

1. Runtime spike and dependency compatibility.
2. Chainlit mounted beside existing FastAPI.
3. Custom React shell connected to Chainlit.
4. DeepAgents runner replacing pydantic-ai chat execution.
5. Domain features ported onto the new runtime: model selection, memory, MCP.
6. Persistence cleanup and migration reset.
7. Planned surface preservation: background tasks, artifacts, provider settings.
8. Removal of old hand-written SSE/tool-calling code.

Each slice must preserve a runnable app. The custom design is non-negotiable: the stock Chainlit UI is not the product UI.

## Current State To Preserve

- Auth/register/login screen and local JWT-style profile behavior.
- Chat list, favorites, rename, delete, auto-title.
- Per-chat model selection from Ollama model list.
- Streaming assistant replies.
- Tool-call UI restored from history.
- Memory facts CRUD, semantic recall, auto-capture, memory-save indicator.
- MCP server management, per-server enable, per-tool curation, refresh/delete, wizard.
- Local-first posture: profiles, chats, facts, MCP headers, and keys stay local.
- Design handoff fidelity in `design/` and existing React components.

## Target File Structure

Backend:

- Create `src/capybara/app.py` - outer FastAPI app factory, custom API routers, and Chainlit mount.
- Create `src/capybara/chainlit_app.py` - Chainlit callbacks: auth/session start/message handling.
- Create `src/capybara/chainlit_config.py` - Chainlit runtime settings, path constants, data-layer wiring.
- Create `src/capybara/agent/deep_runtime.py` - DeepAgents runner facade used by Chainlit callbacks.
- Create `src/capybara/agent/model_registry.py` - provider-agnostic model listing and model factory.
- Create `src/capybara/agent/tools/memory.py` - DeepAgents/LangChain memory recall tool.
- Create `src/capybara/agent/tools/mcp.py` - MCP tool adapter for enabled curated servers.
- Create `src/capybara/persistence/chainlit_layer.py` - Chainlit data layer adapter or schema bridge.
- Keep `src/capybara/services/memory_service.py` initially, then simplify once embeddings/tooling move.
- Keep `src/capybara/services/mcp_service.py` initially, then simplify once MCP tools move.
- Replace `src/capybara/main.py` with a compatibility import from `src/capybara/app.py`.
- Delete old `src/capybara/agent/base.py`, `src/capybara/agent/ollama.py`, `src/capybara/api/sse.py`, and chat SSE routes only after parity tests pass.
- Reset `src/capybara/migrations/versions/` after the new schema is stable.

Frontend:

- Create `frontend/src/chainlit/client.ts` - Chainlit React client initialization.
- Create `frontend/src/chainlit/useChainlitThread.ts` - thread/history/runtime adapter.
- Create `frontend/src/chainlit/convertChainlitMessage.ts` - maps Chainlit messages/steps to current UI message shape.
- Modify `frontend/src/screens/ChatScreen.tsx` - consume Chainlit adapter instead of `useChatStream`.
- Modify `frontend/src/components/Thread.tsx` and related message components only where data shape changes.
- Keep `frontend/src/screens/MemoryScreen.tsx`, `frontend/src/screens/McpScreen.tsx`, and design CSS.
- Delete `frontend/src/api/sse.ts`, `frontend/src/chat/useChatStream.ts`, and custom SSE tests after the Chainlit adapter has full coverage.

Docs:

- Create `docs/superpowers/specs/2026-07-08-chainlit-deepagents-migration-design.md`.
- Update `README.md`.
- Update `AGENTS.md` if it becomes tracked in this branch; ensure it reflects the new stack and current project state.

## Migration Principles

- Keep the custom React design shell. Do not use the stock Chainlit UI as the user-facing app.
- Prefer Chainlit/DeepAgents primitives over custom protocol parsing.
- Keep domain services small. Memory, MCP, profiles, and scheduled tasks are product logic, not chat-transport logic.
- Use a strangler path: add new runtime beside old runtime, switch one boundary at a time, then delete old code.
- Tests come first for every boundary replacement.
- Commit after each task.

---

### Task 0: Confirm Main Baseline And Branch

**Files:**
- No code changes.

- [ ] **Step 1: Confirm the branch**

Run:

```bash
git branch --show-current
```

Expected:

```text
codex/chainlit-deepagents-migration
```

- [ ] **Step 2: Confirm `main` contains the existing MCP frontend work**

Run:

```bash
git log --oneline main -5
```

Expected: the top commit is `0222582 fix(mcp-fe): show tool-count noun in wizard, share pluralTools, harden last_error guard` or a later descendant.

- [ ] **Step 3: Record remaining untracked files**

Run:

```bash
git status --short
```

Expected: only pre-existing untracked local artifacts may appear, such as `.python-version`, `AGENTS.md`, `design/`, or older untracked docs. Do not delete or commit them unless a later task explicitly includes them.

- [ ] **Step 4: Commit**

No commit for this task.

---

### Task 1: Write The Migration Design Spec

**Files:**
- Create: `docs/superpowers/specs/2026-07-08-chainlit-deepagents-migration-design.md`
- Test: documentation review only

- [ ] **Step 1: Create the design spec**

Write `docs/superpowers/specs/2026-07-08-chainlit-deepagents-migration-design.md` with this structure:

```markdown
# Chainlit + DeepAgents Migration - Design

**Date:** 2026-07-08
**Status:** approved for implementation planning

## Problem

CapybaraAgent has accumulated custom runtime code for streaming, tool calls, chat history,
and agent orchestration. The code works, but too much low-level protocol behavior is
hand-written and hard to maintain.

## Goal

Move chat/session/tool orchestration to Chainlit and DeepAgents while preserving the
custom CapybaraAgent React design, local-first data posture, current features, and planned
surfaces.

## Non-goals

- Replacing the product UI with stock Chainlit UI.
- Shipping a cloud-first architecture.
- Dropping memory, MCP curation, local auth, model selection, artifacts, or planned tasks.

## Architecture

FastAPI remains the outer ASGI app. Chainlit is mounted under `/chainlit` and owns chat
session lifecycle, message streaming, steps, and thread persistence. Custom REST routers
continue to serve memory, MCP, model settings, local profiles, and future task APIs.

The frontend remains the existing Vite/React design shell. Its chat runtime adapter moves
from custom fetch/SSE parsing to Chainlit's React client. Existing Memory and MCP screens
continue to call the custom REST APIs.

DeepAgents replaces the pydantic-ai runtime. A small `DeepAgentRunner` receives user
messages, selected model, thread metadata, memory tools, and MCP tools, then streams text
and tool steps into Chainlit.

## Persistence

Chainlit stores threads/messages/steps. Capybara-owned tables store users, settings, facts,
MCP servers/tools, task definitions, provider credentials, and artifact metadata. Because
there are no real deployments, old Alembic revisions can be replaced by a new initial
schema after parity is reached.

## Design Preservation

The first viewport and navigational shell remain Capybara's custom UI. Chainlit is a
runtime and protocol dependency, not the visible design system.

## Migration Strategy

1. Prove Chainlit can be mounted beside FastAPI and consumed by the custom React app.
2. Switch chat transport to Chainlit while keeping domain APIs stable.
3. Switch agent execution to DeepAgents.
4. Port memory and MCP tools to DeepAgents.
5. Reset persistence and remove old hand-written SSE/tool-call code.

## Risks

- Chainlit React client may not expose every thread-metadata operation needed by the
  custom UI. If so, add a small custom REST adapter rather than forking Chainlit.
- Python 3.14 may not be supported by Chainlit/DeepAgents dependency trees. Prefer a
  stable Python 3.12 or 3.13 target if resolution fails.
- Chainlit stock UI customization is insufficient for this product. Use the custom React
  client path.

## Success Criteria

- Existing chat, memory, MCP, auth, and model-selection flows work through the custom UI.
- Tool calls render via Chainlit steps instead of custom SSE `tool-call` parsing.
- Old chat SSE code and pydantic-ai-specific code are removed.
- Backend and frontend tests pass.
```

- [ ] **Step 2: Review the spec**

Run:

```bash
rg -n "TB[D]|TO[D]O|fill[ ]in" docs/superpowers/specs/2026-07-08-chainlit-deepagents-migration-design.md
```

Expected: no matches.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-07-08-chainlit-deepagents-migration-design.md
git commit -m "docs: design chainlit deepagents migration"
```

---

### Task 2: Dependency Compatibility Spike

**Files:**
- Modify: `pyproject.toml`
- Modify: `Dockerfile`
- Modify: `README.md`
- Test: `uv lock`, `uv run python -c "import chainlit, deepagents"`

- [ ] **Step 1: Write the failing dependency import check**

Run before modifying dependencies:

```bash
uv run python -c "import chainlit, deepagents"
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 2: Update backend dependencies**

In `pyproject.toml`, replace pydantic-ai-specific dependencies with Chainlit/DeepAgents dependencies:

```toml
[project]
name = "capybara"
version = "0.1.0"
requires-python = ">=3.12,<3.14"
dependencies = [
    "fastapi>=0.139",
    "uvicorn[standard]>=0.50",
    "chainlit>=2.0",
    "deepagents>=0.1",
    "langchain>=0.3",
    "langchain-core>=0.3",
    "langchain-ollama>=0.2",
    "langchain-openai>=0.2",
    "langchain-mcp-adapters>=0.1",
    "langgraph>=0.2",
    "pydantic-settings>=2.14",
    "sqlalchemy[asyncio]>=2.0.51, <3.0",
    "asyncpg>=0.31",
    "alembic>=1.18",
    "httpx>=0.28",
    "argon2-cffi>=25.1",
    "pyjwt>=2.13",
    "pgvector>=0.3",
]
```

Keep the existing dev dependencies unless resolution forces an upgrade.

- [ ] **Step 3: Align Python runtime**

If `.python-version` is tracked in this branch, set it to:

```text
3.13
```

If it remains untracked, update `Dockerfile` only. Use a Python 3.13 base image:

```dockerfile
FROM python:3.13-slim AS base
```

- [ ] **Step 4: Resolve dependencies**

Run:

```bash
uv lock
```

Expected: PASS. If `chainlit` or `deepagents` does not resolve for Python 3.13, change the target to `>=3.12,<3.13`, use Python 3.12 in `Dockerfile`, rerun `uv lock`, and document the reason in `README.md`.

- [ ] **Step 5: Verify imports**

Run:

```bash
uv run python -c "import chainlit, deepagents; print('ok')"
```

Expected:

```text
ok
```

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock Dockerfile README.md
git commit -m "chore: add chainlit deepagents dependencies"
```

---

### Task 3: Mount Chainlit Beside FastAPI

**Files:**
- Create: `src/capybara/app.py`
- Create: `src/capybara/chainlit_app.py`
- Create: `src/capybara/chainlit_config.py`
- Modify: `src/capybara/main.py`
- Test: `tests/test_chainlit_mount.py`

- [ ] **Step 1: Write the failing mount test**

Create `tests/test_chainlit_mount.py`:

```python
"""Tests for the FastAPI shell mounting the Chainlit runtime."""

from httpx import ASGITransport, AsyncClient

from capybara.app import create_app


async def test_chainlit_is_mounted() -> None:
    """The ASGI app exposes Chainlit under /chainlit."""
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/chainlit")
    assert response.status_code in {200, 307, 308}
```

Run:

```bash
uv run pytest tests/test_chainlit_mount.py -q
```

Expected: FAIL because `capybara.app` does not exist.

- [ ] **Step 2: Create Chainlit config constants**

Create `src/capybara/chainlit_config.py`:

```python
"""Chainlit runtime configuration for CapybaraAgent."""

CHAINLIT_PATH = "/chainlit"
CHAINLIT_TARGET = "src/capybara/chainlit_app.py"
```

- [ ] **Step 3: Create a minimal Chainlit app**

Create `src/capybara/chainlit_app.py`:

```python
"""Chainlit callbacks for CapybaraAgent chat runtime."""

import chainlit as cl


@cl.on_chat_start
async def on_chat_start() -> None:
    """Initialize a Chainlit chat session."""
    cl.user_session.set("model", None)


@cl.on_message
async def on_message(message: cl.Message) -> None:
    """Temporary echo handler used until DeepAgents is wired."""
    response = cl.Message(content="")
    await response.stream_token(message.content)
    await response.send()
```

- [ ] **Step 4: Create the FastAPI shell and mount Chainlit**

Create `src/capybara/app.py`:

```python
"""FastAPI shell that mounts Chainlit and Capybara custom APIs."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from chainlit.utils import mount_chainlit
from fastapi import FastAPI

from capybara.chainlit_config import CHAINLIT_PATH, CHAINLIT_TARGET
from capybara.config import get_settings
from capybara.db.engine import create_engine, create_sessionmaker
from capybara.services.event_bus import EventBus


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize shared runtime state and dispose it on shutdown."""
    settings = get_settings()
    engine = create_engine(settings)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.event_bus = EventBus()
    try:
        yield
    finally:
        await engine.dispose()


def create_app() -> FastAPI:
    """Create the FastAPI shell with custom APIs and Chainlit mounted."""
    app = FastAPI(title="CapybaraAgent", lifespan=lifespan)
    from capybara.api.routers import auth, events, health, mcp, memory, models, users

    app.include_router(health.router)
    app.include_router(events.router)
    app.include_router(memory.router)
    app.include_router(mcp.router)
    app.include_router(models.router)
    app.include_router(users.router)
    app.include_router(auth.router)
    mount_chainlit(app=app, target=CHAINLIT_TARGET, path=CHAINLIT_PATH)
    return app
```

- [ ] **Step 5: Keep `main.py` as compatibility entrypoint**

Replace `src/capybara/main.py` with:

```python
"""ASGI entrypoint for CapybaraAgent."""

from capybara.app import create_app

app = create_app()
```

- [ ] **Step 6: Run the mount test**

Run:

```bash
uv run pytest tests/test_chainlit_mount.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/capybara/app.py src/capybara/chainlit_app.py src/capybara/chainlit_config.py src/capybara/main.py tests/test_chainlit_mount.py
git commit -m "feat: mount chainlit beside fastapi"
```

---

### Task 4: Add A Chainlit React Client Adapter

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/src/chainlit/client.ts`
- Create: `frontend/src/chainlit/convertChainlitMessage.ts`
- Create: `frontend/src/chainlit/useChainlitThread.ts`
- Test: `frontend/src/chainlit/convertChainlitMessage.test.ts`

- [ ] **Step 1: Add frontend dependency**

In `frontend/package.json`, add:

```json
"@chainlit/react-client": "^0.3.0"
```

Run:

```bash
cd frontend
npm install
```

Expected: PASS and `package-lock.json` updated.

- [ ] **Step 2: Write conversion tests**

Create `frontend/src/chainlit/convertChainlitMessage.test.ts`:

```typescript
import { describe, expect, test } from 'vitest'
import { convertChainlitMessage } from './convertChainlitMessage'

describe('convertChainlitMessage', () => {
  test('maps user and assistant messages to the current UI shape', () => {
    expect(
      convertChainlitMessage({
        id: 'u1',
        type: 'user_message',
        output: 'Hello',
        createdAt: '2026-07-08T00:00:00Z',
      }),
    ).toMatchObject({ id: 'u1', role: 'user', content: 'Hello', streaming: false })

    expect(
      convertChainlitMessage({
        id: 'a1',
        type: 'assistant_message',
        output: 'Hi',
        createdAt: '2026-07-08T00:00:00Z',
      }),
    ).toMatchObject({ id: 'a1', role: 'assistant', content: 'Hi', streaming: false })
  })
})
```

Run:

```bash
cd frontend
npm run test -- src/chainlit/convertChainlitMessage.test.ts
```

Expected: FAIL because the converter does not exist.

- [ ] **Step 3: Implement the converter**

Create `frontend/src/chainlit/convertChainlitMessage.ts`:

```typescript
import type { ChatMessage } from '../chat/useChatStream'

type ChainlitLikeMessage = {
  id: string
  type: string
  output?: string
  content?: string
}

/** Convert a Chainlit message into Capybara's current chat message shape. */
export function convertChainlitMessage(message: ChainlitLikeMessage): ChatMessage | null {
  const role =
    message.type === 'user_message'
      ? 'user'
      : message.type === 'assistant_message'
        ? 'assistant'
        : null
  if (role === null) return null
  return {
    id: message.id,
    role,
    content: message.output ?? message.content ?? '',
    streaming: false,
  }
}
```

- [ ] **Step 4: Create client initialization**

Create `frontend/src/chainlit/client.ts`:

```typescript
import { ChainlitAPI } from '@chainlit/react-client'

/** Chainlit client pointed at the mounted runtime path. */
export const chainlitClient = new ChainlitAPI('/chainlit')
```

- [ ] **Step 5: Create a temporary hook facade**

Create `frontend/src/chainlit/useChainlitThread.ts`:

```typescript
import { useCallback, useMemo, useState } from 'react'
import type { ChatMessage } from '../chat/useChatStream'

/** Temporary hook facade. Later tasks replace its internals with live Chainlit client calls. */
export function useChainlitThread() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [sending, setSending] = useState(false)

  const send = useCallback(async (content: string) => {
    setSending(true)
    setMessages((prev) => [
      ...prev,
      { id: `user-${Date.now()}`, role: 'user', content, streaming: false },
      { id: `assistant-${Date.now()}`, role: 'assistant', content, streaming: true },
    ])
    setSending(false)
  }, [])

  return useMemo(
    () => ({ messages, sending, send, loadingHistory: false, cancel: () => {}, regenerate: () => {} }),
    [messages, send, sending],
  )
}
```

- [ ] **Step 6: Run frontend tests**

Run:

```bash
cd frontend
npm run test -- src/chainlit/convertChainlitMessage.test.ts
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/chainlit
git commit -m "feat(frontend): add chainlit client adapter skeleton"
```

---

### Task 5: Replace Custom Chat SSE With Chainlit Runtime

**Files:**
- Modify: `frontend/src/screens/ChatScreen.tsx`
- Modify: `frontend/src/chat/runtime.ts`
- Modify: `frontend/src/components/Thread.tsx`
- Test: `frontend/src/screens/ChatScreen.test.tsx`
- Test: `frontend/src/chainlit/useChainlitThread.test.tsx`

- [ ] **Step 1: Write adapter behavior tests**

Create `frontend/src/chainlit/useChainlitThread.test.tsx`:

```typescript
import { renderHook, act } from '@testing-library/react'
import { describe, expect, test } from 'vitest'
import { useChainlitThread } from './useChainlitThread'

describe('useChainlitThread', () => {
  test('appends a user message when sending', async () => {
    const { result } = renderHook(() => useChainlitThread())

    await act(async () => {
      await result.current.send('Hello')
    })

    expect(result.current.messages[0]).toMatchObject({
      role: 'user',
      content: 'Hello',
    })
  })
})
```

Run:

```bash
cd frontend
npm run test -- src/chainlit/useChainlitThread.test.tsx
```

Expected: PASS with the temporary facade, then update expectations as real Chainlit calls are introduced.

- [ ] **Step 2: Swap ChatScreen to consume the Chainlit hook**

In `frontend/src/screens/ChatScreen.tsx`, replace:

```typescript
import { useChatStream } from '../chat/useChatStream'
```

with:

```typescript
import { useChainlitThread } from '../chainlit/useChainlitThread'
```

Then replace the hook call:

```typescript
const { messages, sending, loadingHistory, send, loadHistory, cancel, regenerate } =
  useChatStream(activeChatId, (title) => {
    if (activeChatId) patchLocal(activeChatId, { title })
  })
```

with:

```typescript
const { messages, sending, loadingHistory, send, loadHistory, cancel, regenerate } =
  useChainlitThread()
```

- [ ] **Step 3: Preserve current UI behavior**

Keep `useChatRuntime` as the bridge into `@assistant-ui/react` until Chainlit message rendering is fully verified. Its inputs remain:

```typescript
const runtime = useChatRuntime({
  messages,
  isRunning: sending,
  onSend: handleSend,
  onReload: regenerate,
  onCancel: cancel,
})
```

- [ ] **Step 4: Run ChatScreen tests**

Run:

```bash
cd frontend
npm run test -- src/screens/ChatScreen.test.tsx src/chainlit/useChainlitThread.test.tsx
```

Expected: PASS after any test fixtures are updated from `/api/chats/.../messages` SSE mocks to Chainlit adapter mocks.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/screens/ChatScreen.tsx frontend/src/chat/runtime.ts frontend/src/components/Thread.tsx frontend/src/chainlit/useChainlitThread.test.tsx
git commit -m "feat(frontend): route chat UI through chainlit adapter"
```

---

### Task 6: Implement DeepAgents Runner

**Files:**
- Create: `src/capybara/agent/deep_runtime.py`
- Create: `src/capybara/agent/model_registry.py`
- Test: `tests/test_deep_runtime.py`

- [ ] **Step 1: Write the runner tests**

Create `tests/test_deep_runtime.py`:

```python
"""Tests for the DeepAgents runner facade."""

from collections.abc import AsyncIterator

from capybara.agent.deep_runtime import DeepAgentRunner, RunnerEvent


class FakeGraph:
    """Small fake graph that yields one text event."""

    async def astream_events(self, _input: dict[str, object], **_kwargs: object) -> AsyncIterator[dict[str, object]]:
        yield {"event": "on_chat_model_stream", "data": {"chunk": "hello"}}


async def test_runner_streams_text_events() -> None:
    """The runner normalizes graph stream events into text events."""
    runner = DeepAgentRunner(graph=FakeGraph())
    events = [event async for event in runner.stream("Hi", model="llama3.1", thread_id="t1")]
    assert events == [RunnerEvent(kind="text", content="hello", name=None, payload=None)]
```

Run:

```bash
uv run pytest tests/test_deep_runtime.py -q
```

Expected: FAIL because `DeepAgentRunner` does not exist.

- [ ] **Step 2: Implement the runner facade**

Create `src/capybara/agent/deep_runtime.py`:

```python
"""DeepAgents runner facade used by Chainlit callbacks."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

from deepagents import create_deep_agent

from capybara.agent.model_registry import ModelRegistry
from capybara.config import Settings


@dataclass(frozen=True)
class RunnerEvent:
    """Normalized event emitted by the agent runtime."""

    kind: str
    content: str | None = None
    name: str | None = None
    payload: dict[str, Any] | None = None


class EventStreamingGraph(Protocol):
    """Protocol for DeepAgents/LangGraph objects that stream events."""

    def astream_events(
        self, input: dict[str, object], **kwargs: object
    ) -> AsyncIterator[dict[str, object]]:
        """Stream LangGraph events."""
        ...


class DeepAgentRunner:
    """Run a DeepAgents graph and normalize its events for Chainlit."""

    def __init__(self, graph: EventStreamingGraph) -> None:
        """Store the compiled graph."""
        self._graph = graph

    async def stream(
        self, content: str, *, model: str, thread_id: str
    ) -> AsyncIterator[RunnerEvent]:
        """Stream normalized text/tool events for one user message."""
        payload = {"messages": [{"role": "user", "content": content}], "model": model}
        async for event in self._graph.astream_events(payload, version="v2", config={"thread_id": thread_id}):
            normalized = self._normalize_event(event)
            if normalized is not None:
                yield normalized

    def _normalize_event(self, event: dict[str, object]) -> RunnerEvent | None:
        """Map LangGraph event dictionaries into Capybara runner events."""
        if event.get("event") == "on_chat_model_stream":
            data = event.get("data")
            if isinstance(data, dict):
                chunk = data.get("chunk")
                if isinstance(chunk, str):
                    return RunnerEvent(kind="text", content=chunk)
                content = getattr(chunk, "content", None)
                if isinstance(content, str) and content:
                    return RunnerEvent(kind="text", content=content)
        return None


def build_graph(settings: Settings, tools: list[object] | None = None) -> EventStreamingGraph:
    """Build the DeepAgents graph for Capybara chat runs."""
    registry = ModelRegistry(settings)
    return create_deep_agent(
        model=registry.chat_model(settings.default_model),
        tools=tools or [],
        system_prompt=(
            "You are CapybaraAgent, a local-first assistant. Use available tools when "
            "they help answer the user's request. Prefer clear, concise answers."
        ),
    )
```

- [ ] **Step 3: Add model registry**

Create `src/capybara/agent/model_registry.py`:

```python
"""Provider-agnostic model listing and construction for the DeepAgents runtime."""

import asyncio

import httpx
from langchain_ollama import ChatOllama, OllamaEmbeddings

from capybara.config import Settings


class ModelRegistry:
    """List and build local-first LLM and embedding providers."""

    def __init__(self, settings: Settings) -> None:
        """Store settings used to reach Ollama."""
        self._settings = settings

    async def list_models(self) -> list[str]:
        """Return chat-capable Ollama model names."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self._settings.ollama_base_url}/api/tags")
            response.raise_for_status()
            names = [entry["name"] for entry in response.json().get("models", [])]
            flags = await asyncio.gather(*(self._supports_chat(client, name) for name in names))
        return [name for name, keep in zip(names, flags, strict=True) if keep]

    async def _supports_chat(self, client: httpx.AsyncClient, name: str) -> bool:
        """Return whether an Ollama model can serve chat completions."""
        response = await client.post(f"{self._settings.ollama_base_url}/api/show", json={"model": name})
        response.raise_for_status()
        capabilities = response.json().get("capabilities")
        return capabilities is None or "completion" in capabilities

    def chat_model(self, name: str) -> ChatOllama:
        """Build a LangChain Ollama chat model."""
        return ChatOllama(model=name, base_url=self._settings.ollama_base_url)

    def embeddings(self) -> OllamaEmbeddings:
        """Build LangChain Ollama embeddings."""
        return OllamaEmbeddings(model=self._settings.embedding_model, base_url=self._settings.ollama_base_url)
```

- [ ] **Step 4: Run tests**

Run:

```bash
uv run pytest tests/test_deep_runtime.py -q
uv run ruff check src/capybara/agent/deep_runtime.py src/capybara/agent/model_registry.py
uv run mypy src/capybara/agent/deep_runtime.py src/capybara/agent/model_registry.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/capybara/agent/deep_runtime.py src/capybara/agent/model_registry.py tests/test_deep_runtime.py
git commit -m "feat(agent): add deepagents runner facade"
```

---

### Task 7: Wire Chainlit Messages To DeepAgents

**Files:**
- Modify: `src/capybara/chainlit_app.py`
- Modify: `src/capybara/app.py`
- Test: `tests/test_chainlit_deepagents_flow.py`

- [ ] **Step 1: Write a callback-level flow test**

Create `tests/test_chainlit_deepagents_flow.py`:

```python
"""Tests for the Chainlit-to-DeepAgents message flow."""

from capybara.agent.deep_runtime import RunnerEvent


class FakeRunner:
    """Runner fake that streams one text event."""

    async def stream(self, content: str, *, model: str, thread_id: str):
        """Yield a deterministic response."""
        assert content == "Hello"
        assert model == "llama3.1"
        assert thread_id == "thread-1"
        yield RunnerEvent(kind="text", content="Hi")


async def test_fake_runner_contract() -> None:
    """Document the runner contract consumed by Chainlit callbacks."""
    events = [event async for event in FakeRunner().stream("Hello", model="llama3.1", thread_id="thread-1")]
    assert events == [RunnerEvent(kind="text", content="Hi", name=None, payload=None)]
```

Run:

```bash
uv run pytest tests/test_chainlit_deepagents_flow.py -q
```

Expected: PASS. This pins the contract before wiring Chainlit.

- [ ] **Step 2: Add app-state runner construction**

In `src/capybara/app.py`, add model registry and runner construction during lifespan after settings are loaded:

```python
from capybara.agent.deep_runtime import DeepAgentRunner, build_graph
from capybara.agent.model_registry import ModelRegistry

# inside lifespan:
app.state.model_registry = ModelRegistry(settings)
app.state.deep_agent_runner = DeepAgentRunner(graph=build_graph(settings))
```

- [ ] **Step 3: Replace the temporary echo callback**

In `src/capybara/chainlit_app.py`, replace the echo `on_message` with:

```python
"""Chainlit callbacks for CapybaraAgent chat runtime."""

import chainlit as cl

from capybara.agent.deep_runtime import DeepAgentRunner


@cl.on_chat_start
async def on_chat_start() -> None:
    """Initialize a Chainlit chat session."""
    cl.user_session.set("model", "llama3.1")


@cl.on_message
async def on_message(message: cl.Message) -> None:
    """Run one message through the DeepAgents runtime and stream it through Chainlit."""
    runner = cl.user_session.get("deep_agent_runner")
    if not isinstance(runner, DeepAgentRunner):
        raise RuntimeError("DeepAgentRunner is not configured")
    model = cl.user_session.get("model") or "llama3.1"
    thread_id = cl.context.session.id
    response = cl.Message(content="")
    async for event in runner.stream(message.content, model=model, thread_id=thread_id):
        if event.kind == "text" and event.content:
            await response.stream_token(event.content)
    await response.send()
```

- [ ] **Step 4: Ensure Chainlit session can see app-state dependencies**

Add a startup bridge in `chainlit_app.py` that reads dependencies from the mounted FastAPI app or constructs them from settings. Prefer passing only stable factories into `cl.user_session`: `ModelRegistry`, `DeepAgentRunner`, memory service factory, MCP service factory.

- [ ] **Step 5: Run tests**

Run:

```bash
uv run pytest tests/test_chainlit_mount.py tests/test_chainlit_deepagents_flow.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/capybara/app.py src/capybara/chainlit_app.py src/capybara/agent/deep_runtime.py tests/test_chainlit_deepagents_flow.py
git commit -m "feat(chainlit): stream messages through deepagents"
```

---

### Task 8: Port Model Selection

**Files:**
- Modify: `src/capybara/api/routers/models.py`
- Modify: `src/capybara/chainlit_app.py`
- Modify: `frontend/src/components/Composer.tsx`
- Modify: `frontend/src/chainlit/useChainlitThread.ts`
- Test: `tests/test_models.py`
- Test: `frontend/src/components/Composer.test.tsx`

- [ ] **Step 1: Update backend model listing tests**

Change tests that currently assert pydantic-ai `OllamaAgent` behavior to assert `ModelRegistry.list_models()`.

Run:

```bash
uv run pytest tests/test_models.py tests/test_agent_models.py -q
```

Expected: FAIL until the router uses `ModelRegistry`.

- [ ] **Step 2: Update `/models` router**

Change `src/capybara/api/routers/models.py` to depend on `ModelRegistry` instead of `BaseAgent`:

```python
"""Router for listing available LLM models."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from httpx import HTTPError

from capybara.agent.model_registry import ModelRegistry
from capybara.api.dependencies import get_current_user, get_model_registry
from capybara.api.schemas import ModelsOut
from capybara.db.models import User

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=ModelsOut)
async def list_models(
    _user: Annotated[User, Depends(get_current_user)],
    registry: Annotated[ModelRegistry, Depends(get_model_registry)],
) -> ModelsOut:
    """Return models currently available from the local provider."""
    try:
        names = await registry.list_models()
    except HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Ollama unreachable") from exc
    return ModelsOut(provider="ollama", models=names)
```

- [ ] **Step 3: Store selected model in Chainlit session/thread metadata**

When the frontend changes the model, send it to a small custom endpoint:

```http
PATCH /thread-settings/{thread_id}
{"model":"llama3.1"}
```

Always create this endpoint rather than depending on Chainlit React-client metadata coverage. The endpoint writes the model into a Capybara `thread_settings` table keyed by Chainlit thread id, and `chainlit_app.py` reads that setting at message time.

- [ ] **Step 4: Update frontend adapter**

`frontend/src/chainlit/useChainlitThread.ts` must expose:

```typescript
selectModel(model: string): Promise<void>
selectedModel: string | null
```

`Composer` keeps its current design and calls `selectModel`.

- [ ] **Step 5: Run tests**

Run:

```bash
uv run pytest tests/test_models.py -q
cd frontend
npm run test -- src/components/Composer.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/capybara/api/routers/models.py src/capybara/api/dependencies.py src/capybara/chainlit_app.py frontend/src/components/Composer.tsx frontend/src/chainlit/useChainlitThread.ts tests/test_models.py frontend/src/components/Composer.test.tsx
git commit -m "feat: port model selection to chainlit runtime"
```

---

### Task 9: Port Memory To DeepAgents Tools

**Files:**
- Create: `src/capybara/agent/tools/memory.py`
- Modify: `src/capybara/services/memory_service.py`
- Modify: `src/capybara/chainlit_app.py`
- Test: `tests/test_memory_recall_tool.py`
- Test: `tests/test_memory_service.py`

- [ ] **Step 1: Write memory tool test**

Update `tests/test_memory_recall_tool.py` to assert the new tool callable:

```python
"""Tests for the DeepAgents memory recall tool."""

from uuid import uuid4

from capybara.agent.tools.memory import make_memory_recall_tool


class FakeMemoryService:
    """Memory service fake."""

    async def recall(self, user_id, query: str):
        """Return deterministic facts."""
        assert query == "project"
        return [type("Fact", (), {"category": "project", "content": "CapybaraAgent migration"})()]


async def test_memory_recall_tool_formats_facts() -> None:
    """The recall tool returns model-readable facts."""
    tool = make_memory_recall_tool(FakeMemoryService(), uuid4())
    result = await tool.ainvoke({"query": "project"})
    assert "CapybaraAgent migration" in result
```

Run:

```bash
uv run pytest tests/test_memory_recall_tool.py -q
```

Expected: FAIL until the tool exists.

- [ ] **Step 2: Implement the memory tool**

Create `src/capybara/agent/tools/memory.py`:

```python
"""Memory tools exposed to DeepAgents."""

from typing import Protocol
from uuid import UUID

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class RecallArgs(BaseModel):
    """Arguments for memory recall."""

    query: str = Field(description="Search query for the user's long-term memory.")


class MemoryServiceProtocol(Protocol):
    """Memory service behavior needed by the recall tool."""

    async def recall(self, user_id: UUID, query: str) -> list[object]:
        """Return relevant facts."""
        ...


def _format_facts(facts: list[object]) -> str:
    """Format facts for model consumption."""
    if not facts:
        return "No relevant facts found."
    lines = []
    for fact in facts:
        category = getattr(fact, "category", "fact")
        content = getattr(fact, "content", str(fact))
        lines.append(f"- [{category}] {content}")
    return "\n".join(lines)


def make_memory_recall_tool(memory: MemoryServiceProtocol, user_id: UUID) -> StructuredTool:
    """Build a DeepAgents-compatible recall tool."""

    async def recall(query: str) -> str:
        """Search the user's long-term memory for relevant facts."""
        return _format_facts(await memory.recall(user_id, query))

    return StructuredTool.from_function(
        coroutine=recall,
        name="recall",
        description="Search the user's long-term memory for relevant facts.",
        args_schema=RecallArgs,
    )
```

- [ ] **Step 3: Switch embeddings to LangChain Ollama**

Update `MemoryService` to accept `ModelRegistry` or an embeddings provider instead of `BaseAgent.embed`. Keep `run_structured` behind a small extraction service so the auto-capture logic remains deterministic.

- [ ] **Step 4: Surface tool steps through Chainlit**

In `chainlit_app.py`, when `DeepAgentRunner` emits a tool start/end event, create a `cl.Step` with the tool name and input/output. The frontend should render this via Chainlit step data instead of custom SSE `tool-call` frames.

- [ ] **Step 5: Run memory tests**

Run:

```bash
uv run pytest tests/test_memory_recall_tool.py tests/test_memory_service.py tests/test_memory_api.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/capybara/agent/tools/memory.py src/capybara/services/memory_service.py src/capybara/chainlit_app.py tests/test_memory_recall_tool.py tests/test_memory_service.py tests/test_memory_api.py
git commit -m "feat(memory): expose recall through deepagents"
```

---

### Task 10: Port MCP Tools To DeepAgents

**Files:**
- Create: `src/capybara/agent/tools/mcp.py`
- Modify: `src/capybara/services/mcp_service.py`
- Modify: `src/capybara/chainlit_app.py`
- Test: `tests/test_mcp_service.py`
- Test: `tests/test_mcp_adapter.py`

- [ ] **Step 1: Write curated MCP tool test**

Update `tests/test_mcp_service.py` so `McpService.build_tools(user_id)` returns LangChain-compatible tools for enabled servers/tools only.

Run:

```bash
uv run pytest tests/test_mcp_service.py -q
```

Expected: FAIL until `build_tools` exists.

- [ ] **Step 2: Implement MCP tool adapter**

Create `src/capybara/agent/tools/mcp.py`:

```python
"""MCP tools exposed to DeepAgents."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from langchain_core.tools import BaseTool


class McpServiceProtocol(Protocol):
    """MCP service behavior needed by the DeepAgents runtime."""

    async def build_tools(self, user_id: UUID) -> Sequence[BaseTool]:
        """Build enabled MCP tools for a user."""
        ...


async def load_mcp_tools(service: McpServiceProtocol, user_id: UUID) -> list[BaseTool]:
    """Return enabled MCP tools for the agent."""
    return list(await service.build_tools(user_id))
```

- [ ] **Step 3: Replace pydantic-ai MCP toolsets**

In `McpService`, replace `build_toolsets` with `build_tools` using LangChain MCP adapters. Preserve existing behavior:

- only enabled servers are considered;
- only enabled tools are exposed;
- tool names are namespaced by server slug;
- attach/refresh errors stay loud;
- turn-time preflight failures are logged and skipped.

- [ ] **Step 4: Preserve MCP frontend API**

Do not change `/mcp/servers` API shapes. `McpScreen`, `ConnectWizard`, `McpServerCard`, and `McpToolChip` should keep working.

- [ ] **Step 5: Run MCP tests**

Run:

```bash
uv run pytest tests/test_mcp_service.py tests/test_mcp_adapter.py tests/test_mcp_api.py -q
cd frontend
npm run test -- src/mcp src/screens/McpScreen.test.tsx src/components/McpServerCard.test.tsx src/components/ConnectWizard.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/capybara/agent/tools/mcp.py src/capybara/services/mcp_service.py src/capybara/chainlit_app.py tests/test_mcp_service.py tests/test_mcp_adapter.py tests/test_mcp_api.py
git commit -m "feat(mcp): expose curated tools through deepagents"
```

---

### Task 11: Move Chat Persistence To Chainlit Data Layer

**Files:**
- Create: `src/capybara/persistence/chainlit_layer.py`
- Modify: `src/capybara/db/models/chat.py`
- Modify: `src/capybara/db/models/message.py`
- Modify: `src/capybara/repositories/chat_repo.py`
- Modify: `src/capybara/repositories/message_repo.py`
- Test: `tests/test_repositories.py`
- Test: `tests/test_chats_api.py`

- [ ] **Step 1: Write persistence parity tests**

Add tests that assert:

- a Chainlit thread can be listed in the sidebar;
- a Chainlit thread can be renamed;
- favorite state is preserved;
- Chainlit steps/tool calls are restored into the UI shape;
- memory saves still attach to the assistant message or equivalent Chainlit step.

Run:

```bash
uv run pytest tests/test_repositories.py tests/test_chats_api.py -q
```

Expected: FAIL until the data-layer bridge exists.

- [ ] **Step 2: Implement Chainlit data-layer bridge**

Create `src/capybara/persistence/chainlit_layer.py` with a thin adapter around Chainlit's data persistence. The adapter must expose only Capybara's needed operations:

```python
"""Capybara bridge around Chainlit thread persistence."""

from typing import Protocol


class ThreadStore(Protocol):
    """Thread operations needed by Capybara's custom UI."""

    async def list_threads(self, user_id: str) -> list[dict[str, object]]:
        """Return sidebar thread summaries."""
        ...

    async def update_thread_metadata(self, thread_id: str, metadata: dict[str, object]) -> None:
        """Update model/favorite/title metadata."""
        ...
```

Use this bridge from custom endpoints instead of querying `chats` and `messages` tables directly.

- [ ] **Step 3: Keep compatibility endpoints temporarily**

Keep `/chats` endpoints as adapters over Chainlit threads while the frontend is still migrating. Once the frontend no longer calls them, delete the endpoints in Task 14.

- [ ] **Step 4: Run repository/API tests**

Run:

```bash
uv run pytest tests/test_repositories.py tests/test_chats_api.py -q
```

Expected: PASS after tests are updated to the new persistence contract.

- [ ] **Step 5: Commit**

```bash
git add src/capybara/persistence/chainlit_layer.py src/capybara/repositories src/capybara/api/routers/chats.py tests/test_repositories.py tests/test_chats_api.py
git commit -m "feat(persistence): bridge chats to chainlit threads"
```

---

### Task 12: Reset Database Migrations

**Files:**
- Delete: old files under `src/capybara/migrations/versions/`
- Create: `src/capybara/migrations/versions/20260708_0001_initial_chainlit_runtime.py`
- Test: `tests/test_migrations.py`

- [ ] **Step 1: Write migration smoke test**

Update `tests/test_migrations.py` to assert `alembic upgrade head` creates:

- Chainlit data-layer tables;
- Capybara users/profile settings;
- facts with pgvector;
- MCP servers/tools;
- provider settings;
- task definitions;
- artifact metadata;
- thread metadata extension table if used.

- [ ] **Step 2: Delete old revisions**

Delete every previous revision under:

```text
src/capybara/migrations/versions/
```

This is allowed because the project has no real deployed database.

- [ ] **Step 3: Create one new initial migration**

Create `src/capybara/migrations/versions/20260708_0001_initial_chainlit_runtime.py` with a complete initial schema. Include `CREATE EXTENSION IF NOT EXISTS vector`.

- [ ] **Step 4: Run migration tests**

Run:

```bash
uv run pytest tests/test_migrations.py -q
uv run alembic upgrade head
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/capybara/migrations tests/test_migrations.py
git commit -m "chore(db): reset migrations for chainlit runtime"
```

---

### Task 13: Preserve Planned Surfaces

**Files:**
- Create: `src/capybara/tasks/models.py`
- Create: `src/capybara/tasks/service.py`
- Create: `src/capybara/artifacts/models.py`
- Create: `src/capybara/providers/service.py`
- Modify: `design/design_handoff_capybaraagent/README.md` only if it is tracked
- Test: new tests under `tests/test_tasks_service.py`, `tests/test_provider_settings.py`

- [ ] **Step 1: Add task and provider contracts**

Create service-level contracts only. Do not build the full UI unless it is already in scope for the current execution wave.

`src/capybara/tasks/service.py`:

```python
"""Background task scheduling contracts for future Capybara task UI."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class ScheduledTask:
    """A user-owned scheduled prompt."""

    id: UUID
    user_id: UUID
    title: str
    cron: str
    prompt: str
    enabled: bool
    next_run_at: datetime | None
```

`src/capybara/providers/service.py`:

```python
"""Provider settings contracts for LLM configuration UI."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderConfig:
    """A local LLM provider configuration."""

    name: str
    kind: str
    base_url: str | None
    default_model: str | None
    enabled: bool
```

- [ ] **Step 2: Document planned integration**

Update the migration design spec with a section:

```markdown
## Planned Surfaces

Background tasks, artifacts, and provider settings stay first-class Capybara domain
modules. Chainlit handles chat runtime; it does not replace scheduling, provider
configuration, or artifact persistence.
```

- [ ] **Step 3: Commit**

```bash
git add src/capybara/tasks src/capybara/artifacts src/capybara/providers docs/superpowers/specs/2026-07-08-chainlit-deepagents-migration-design.md
git commit -m "docs: preserve planned product surfaces in migration"
```

---

### Task 14: Delete Old Hand-Written Runtime

**Files:**
- Delete: `src/capybara/api/sse.py`
- Delete: old chat SSE branches in `src/capybara/api/routers/chats.py`
- Delete: `src/capybara/agent/base.py`
- Delete: `src/capybara/agent/ollama.py`
- Delete: pydantic-ai-specific MCP adapter if replaced
- Delete: `frontend/src/api/sse.ts`
- Delete: `frontend/src/chat/useChatStream.ts`
- Modify: tests that imported old SSE/tool-call internals

- [ ] **Step 1: Find old runtime references**

Run:

```bash
rg -n "pydantic_ai|format_sse|useChatStream|parseSse|tool-call|tool-result|BaseAgent|OllamaAgent" src tests frontend/src
```

Expected: matches before deletion.

- [ ] **Step 2: Delete old runtime files**

Delete files only after Tasks 3-13 pass.

- [ ] **Step 3: Update imports**

Replace remaining imports with Chainlit/DeepAgents equivalents:

- `BaseAgent` -> `DeepAgentRunner` or `ModelRegistry`;
- `OllamaAgent` -> `ModelRegistry`;
- custom SSE event parsing -> Chainlit client message/step stream.

- [ ] **Step 4: Verify no old references remain**

Run:

```bash
rg -n "pydantic_ai|format_sse|useChatStream|parseSse|BaseAgent|OllamaAgent" src tests frontend/src
```

Expected: no matches, except historical docs under `docs/superpowers/`.

- [ ] **Step 5: Run full quality gates**

Run:

```bash
uv run ruff check .
uv run mypy src
uv run pytest
cd frontend
npm run lint
npm run typecheck
npm run test
npm run build
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src tests frontend docs README.md pyproject.toml uv.lock
git commit -m "refactor: remove legacy sse pydantic-ai runtime"
```

---

### Task 15: Manual End-To-End Verification

**Files:**
- Modify: `README.md`
- Modify: `docker-compose.yml`
- Test: manual browser verification

- [ ] **Step 1: Start the stack**

Run:

```bash
docker compose up --build
```

Expected:

- frontend is served at `http://localhost:3000`;
- API shell is served at `http://localhost:8000`;
- Chainlit runtime is mounted under `http://localhost:8000/chainlit`;
- Postgres starts with pgvector.

- [ ] **Step 2: Verify current flows**

In the custom UI:

- register a user;
- log in;
- select an Ollama model;
- create a chat;
- send a message and see streaming text;
- trigger memory recall and see a tool/step card;
- add/edit/delete a memory fact;
- connect an MCP server;
- toggle an MCP tool;
- send a message that can call an enabled tool;
- reload the page and verify history/tool steps/memory saves are restored.

- [ ] **Step 3: Verify design preservation**

Compare against the design handoff:

- auth view;
- sidebar;
- welcome chat;
- active chat;
- memory screen;
- MCP screen and wizard.

No stock Chainlit screen should be visible in the main product flow.

- [ ] **Step 4: Update README**

Document:

- Chainlit mounted runtime;
- custom React UI remains the product UI;
- DeepAgents runtime;
- Python version target;
- new dev commands;
- how to reset the local database after migration reset.

- [ ] **Step 5: Commit**

```bash
git add README.md docker-compose.yml
git commit -m "docs: document chainlit deepagents runtime"
```

---

## Final Verification

Run from repo root:

```bash
uv run ruff check .
uv run mypy src
uv run pytest
cd frontend
npm run lint
npm run typecheck
npm run test
npm run build
docker compose config
```

Expected: all commands pass.

## Self-Review Notes

- Spec coverage: current chat, auth, model selection, memory, MCP, tool rendering, design shell, and planned task/provider/artifact surfaces are mapped to tasks.
- Risk handling: stock Chainlit UI is rejected; Python compatibility is verified before large rewrites; Chainlit metadata gaps are handled by small custom REST adapters instead of forking.
- Cleanup: old SSE and pydantic-ai runtime are deleted only after Chainlit/DeepAgents parity is tested.
- Scope: this is a migration plan, not a single implementation task. Execute in order and commit after each task.
