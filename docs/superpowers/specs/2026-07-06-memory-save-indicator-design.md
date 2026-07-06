# Memory-save indicator — design

**Date:** 2026-07-06
**Status:** Approved design, pending implementation plan
**Slice:** Memory UX — surface auto-capture ("что запомнилось") symmetrically with recall

## Problem

The assistant already shows when it **retrieves** facts from long-term memory: `recall`
is a real pydantic-ai tool the model calls mid-turn, so it flows through the per-turn SSE
stream as `tool-call` / `tool-result` frames and renders as a collapsible chip
(`ToolCallCard`, label «Поиск в памяти»).

It shows **nothing** when it **saves** a fact. Saving is not a tool call: it is a
deterministic background job (`MemoryService.extract_and_store`) that runs in a Starlette
`BackgroundTask` *after* the per-turn SSE response has already closed. The model never
invokes a "save" function, and by the time facts are stored the stream is gone — so there
is no channel and no UI surface for it.

## Goal

Surface auto-capture in the UI with the same honesty and durability as recall: a chip on
the assistant message showing «Запомнил N фактов», expandable to the saved facts, that
also survives a history reload.

## Non-goals

- Turning saving into a model-invoked tool (extraction stays deterministic and reliable).
- A general notification/inbox subsystem. Only the **delivery channel** is built generic;
  persistence stays memory-specific until a real background-tasks slice defines its needs.
- Surfacing saves for `regenerate` (that path does not run extraction today — see
  Known limitations).
- Multi-worker / multi-replica delivery (the pub/sub is process-local — see Known
  limitations).

## Key decisions (from brainstorming)

1. **Keep deterministic background extraction**; surface it via a dedicated event rather
   than converting saving to an LLM tool.
2. **Keep extraction post-response** (do not inline it into the reply stream / add latency);
   deliver the event over a **separate channel**.
3. **Channel = a per-user persistent SSE endpoint `/events` backed by an in-process
   pub/sub (`EventBus`).** Reusable for future cron/background-task notifications — they
   just publish new event types on the same channel.
4. **UI = a chip on the assistant message, symmetric with recall**, expandable to the saved
   facts. Because saving happens *after* the answer (unlike recall, which precedes it), the
   chip renders as a **footer below the assistant text**, not above it.
5. **Persistence = a new `memory_saves` field on `Message`** (option B). Memory-specific for
   now (YAGNI); the reusable part is the channel, not the storage schema.

## Architecture / data flow

```
send_message (per-turn SSE)                         GET /events (per-user persistent SSE)
  │  stream reply … → done{message_id}                 │  (opened once on app mount, reconnects)
  ▼                                                     │
BackgroundTask: extract_and_store(user, chat)          │
  │  1. extract candidate facts (chat's model)         │
  │  2. dedup + persist novel facts (source="auto")    │
  │  3. if ≥1 saved:                                    │
  │       a. UPDATE assistant Message.memory_saves ─────┼─► persisted (survives reload)
  │       b. EventBus.publish(user_id, memory-save) ────┼─► live push to subscriber(s)
  ▼                                                     ▼
 (task ends)                              frontend: locate message by message_id,
                                          attach memorySaves → render footer chip
```

**Persistence is the source of truth; the live push is best-effort.** If no subscriber is
connected when the event is published (reconnect race, tab closed, user on another chat),
the live event is simply dropped — the chip still appears on the next history load because
`memory_saves` is persisted on the message. This keeps the design robust without delivery
guarantees.

## Backend

### `EventBus` (new) — `src/capybara/services/event_bus.py`

In-process async pub/sub, keyed by `user_id`.

- `async def publish(self, user_id: UUID, event: dict[str, Any]) -> None` — fan out to
  every active subscriber queue for that user; never blocks the publisher on a slow
  consumer (bounded queue; drop-oldest or drop-newest on overflow — decide in plan).
- `subscribe(self, user_id: UUID)` — an async context manager yielding an
  `asyncio.Queue`; registers the queue on enter and removes it on exit (so a disconnected
  client is always cleaned up).
- Holds no DB state. Created once in the app lifespan and stored on `app.state`; exposed
  via a `get_event_bus` FastAPI dependency. The **same singleton** is injected into
  `MemoryService` (so the background task publishes to the queues `/events` reads).

### `GET /events` (new) — `src/capybara/api/routers/events.py`

- Depends on `get_current_user` + `get_event_bus`.
- Subscribes for `user.id`, streams each published event as an SSE frame
  (`event: <type>` / `data: <json>`), and emits periodic keepalive comments
  (`: keepalive\n\n`) so proxies/browsers hold the connection open. Reuses the existing
  `_SSE_HEADERS` (no-cache / no-buffering / keep-alive).
- On disconnect/cancel, the `subscribe` context manager unsubscribes in a `finally`.

### `Message.memory_saves` (new column) — `src/capybara/db/models/message.py`

- `memory_saves: Mapped[list[dict[str, Any]] | None]` — JSONB, nullable. Display-only
  record (like `tool_calls`), never replayed into model context. Each entry:
  `{"content": str, "category": "personal"|"project"|"preference"}`.
- New Alembic migration adds the nullable column (no backfill).

### `MemoryService.extract_and_store` (changed) — `src/capybara/services/memory_service.py`

- Accepts an optional `event_bus: EventBus | None` via `__init__` (mirrors how the service
  already takes agent/settings; stays `None`-safe for tests that don't wire it).
- While storing, **collect the facts actually persisted** (i.e. those that survived dedup),
  as `{content, category}`.
- Capture the **last assistant message** (id) for the turn — `_last_turn_text` already
  locates it; refactor to also return that `Message` so we know which row to annotate.
- If ≥1 fact was saved:
  1. `UPDATE` that assistant message's `memory_saves` with the collected list, commit.
  2. `event_bus.publish(user_id, event)` where `event` names its type (`"memory-save"`)
     plus `chat_id`, `message_id`, and `facts` — the `/events` router renders it into the
     SSE frame shown under **Event contract**.
- If 0 facts saved: no update, no publish (honest — nothing to show).
- Persist **before** publish so any consumer sees consistent state. Publishing is
  best-effort; a publish failure must not fail the task (it's already wrapped by
  `schedule_extraction`'s try/except).

### Schemas — `src/capybara/api/schemas.py`

- `MemorySaveOut { content: str; category: str }`.
- `MessageOut` gains `memory_saves: list[MemorySaveOut] | None = None` (so `GET /chats/{id}`
  carries it and the frontend reconstructs the chip on reload).

### Wiring — `dependencies.py`, `main.py`

- `main.py` lifespan: construct the `EventBus`, store on `app.state`.
- `get_event_bus` dependency returns the singleton.
- `get_memory_service` injects the singleton bus into `MemoryService`.
- Register the `events` router.

## Event contract (`/events` channel)

```
event: memory-save
data: {"chat_id": "<uuid>", "message_id": "<uuid>",
       "facts": [{"content": "...", "category": "personal"}]}
```

The channel is generic: future background-task notifications add new `event:` names on the
same stream without touching this one.

## Frontend

- **Global subscription:** open `/events` once on app mount (no login yet → single local
  user), with reconnect-on-drop. A small app-level hook/provider owns the connection,
  separate from the per-send `useChatStream` fetch stream.
- **Client state:** `ChatMessage` gains `memorySaves?: { content: string; category: string }[]`.
- **On `memory-save`:** find the message by `message_id`; set its `memorySaves`. If the
  message isn't in the current view, drop it (history reload will restore it).
- **History load (`loadHistory`):** map `MessageOut.memory_saves` → `memorySaves`, so the
  chip renders after reload with no live event.
- **Rendering:** a footer chip **below** the assistant text (recall renders above), reusing
  the `ToolCallCard` collapsible markup. Label «Запомнил N фактов»; expands to the list of
  saved facts (content + category). No running/spinner state — it is a terminal,
  post-response indicator, which also avoids a "started but saved 0" retraction.
- **Types (`api/types.ts`):** add `MemorySaveOut` and `MessageOut.memory_saves`.

## Known limitations

- **`regenerate` does not run extraction** today (only `send_message` attaches
  `schedule_extraction`), so no memory-save chip appears for regenerated replies. This
  preserves current behavior; revisit if/when regenerate should also capture.
- **Auto-capture off** → no extraction → no chip (correct).
- **Process-local pub/sub:** works for the single `api` container. Horizontal scaling needs
  a shared broker (Redis pub/sub), swapped in when the Celery/tasks slice lands — the same
  forward-compat stance as `schedule_extraction` being a stand-in for a real task queue.

## Testing (TDD)

- **`EventBus`:** publish/subscribe delivery; multiple subscribers for one user; per-user
  isolation (user A never receives user B's events); unsubscribe on context exit.
- **`extract_and_store`:** persists + publishes the saved facts and annotates the correct
  assistant message; dedup still skips near-duplicates; respects the auto-capture flag;
  publishes/annotates nothing when the extraction yields no novel facts. Use
  `FunctionModel`/`TestModel` for extraction against a real Postgres (testcontainers).
- **`GET /events`:** a subscribed client receives a subsequently-published event; disconnect
  removes the subscription (no leak).
- **Integration:** `send_message` → after the background task, `GET /chats/{id}` returns the
  assistant message with populated `memory_saves`.
- **Frontend:** the `memory-save` handler attaches `memorySaves` to the right message and
  renders the footer chip; `loadHistory` restores the chip from `memory_saves`.

## Files touched (summary)

**New:** `services/event_bus.py`, `api/routers/events.py`, one Alembic migration,
frontend global `/events` subscription hook + footer chip component.

**Changed:** `db/models/message.py`, `api/schemas.py`, `services/memory_service.py`,
`api/dependencies.py`, `main.py`; frontend `useChatStream` (history mapping + state),
`api/types.ts`, message rendering.
