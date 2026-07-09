# Memory (facts) — long-term memory with recall tool + auto-capture — design

**Date:** 2026-07-05
**Status:** approved (brainstorm)

## Problem

CapybaraAgent is pitched as a local-first **agent**, but today it has no memory: every chat
starts blank and the assistant knows nothing about the user across turns or chats. The design
handoff (`design/CapybaraAgent.dc.html` §5c "Память") specifies a Memory area — user-visible,
editable **fact cards** (category tag, text, date, edit/delete) plus an "Авто-запоминание"
toggle — and the product vision lists memory (facts + recall) as a core capability.

## Goal

Ship a cohesive **Memory** vertical slice: persistent, user-scoped **facts** stored with vector
embeddings in Postgres (pgvector); the agent can **recall** relevant facts via a tool during a
chat; facts are managed on a dedicated **"Память"** screen (list / add / edit / delete); and,
when enabled, facts are **auto-captured** from conversations. Local-first throughout —
embeddings and extraction run against the host Ollama, nothing leaves the device.

## Scope

**In scope (backend + frontend + tests):**
- `facts` table (user-scoped) with a pgvector `embedding` column + HNSW index; `pgvector`
  extension; Alembic migration.
- `users.memory_auto_capture BOOLEAN` toggle column.
- Embeddings via the provider abstraction (`BaseAgent.embed`), Ollama `nomic-embed-text`.
- A **generic tool-registration seam** on `stream_reply` (a list of tools), populated in this
  slice with a single **recall** tool.
- **Auto-capture** of facts after a reply (variant A: post-stream `BackgroundTask`), gated by
  the per-user toggle, with embedding-similarity dedup.
- `/memory` API: facts CRUD + settings (toggle).
- A standalone **"Память"** screen reached from the sidebar; fact-card grid, add/edit/delete,
  auto-remember toggle; `useFacts` hook + `memoryApi` with optimistic updates + rollback.

**Out of scope (later slices):**
- Auto-**injection** of memories into the prompt (this slice is **recall-tool only**).
- The full Settings shell (LLM / MCP / Tasks rail) — a standalone Память screen only.
- Real background-task queue (Celery) — variant A is a marked-temporary stand-in behind a seam.
- Semantic consolidation, temporal/graph memory, mem0/Letta/Zep.
- i18n of the memory UI (RU only, consistent with the current app).
- Encryption of facts at rest.

## Decisions

- **DIY on pgvector, not a memory framework.** The stack already has SQLAlchemy-async +
  Postgres + Alembic + repository pattern + pydantic-ai; the canonical pgvector RAG pattern is
  ~150 LOC from scratch and even less friction here. mem0/Letta/Zep would add a separate service
  and own the store, clashing with local-first + the layered architecture + user-editable facts.
  Retrieval and extraction sit behind clean seams so a library can be swapped in later.
- **pgvector from day one** (per product owner): even at small fact counts, semantic recall beats
  keyword, and building the vector path now avoids a migration later.
- **pydantic-ai stays the LLM layer** — it already covers provider-agnosticism (Ollama/OpenAI/…)
  plus tool-calling and structured output. No LiteLLM (it would duplicate pydantic-ai).
- **Recall-tool only** (no auto-injection). The agent decides when to search memory. Known
  tradeoff: small Ollama models may not reliably call tools; mitigated by a system-prompt nudge,
  and the shared retrieval seam lets us add auto-injection later with no rework.
- **Generic tools seam.** `stream_reply` takes a **list of tools**, not a memory-specific
  `recall` param, so future tools (GPT function tools, MCP, web search, code) drop into the same
  list. pydantic-ai's tool-calling is provider-agnostic, so tools work across Ollama/OpenAI
  unchanged. This slice populates the list with **only** the recall tool (YAGNI on content, no
  lock-in on the interface).
- **Fixed category set:** `personal` (Личное), `project` (Проект), `preference` (Предпочтения),
  coloured per the mockup (accent `#D89B6C` / blue `#7fa8d0` / green `#8fbf9e`).
- **Auto-capture toggle = a column on `users`** (`memory_auto_capture`, default `true`). YAGNI
  for a single flag; a settings table can come with the Settings slice.
- **Auto-capture execution = variant A (post-stream `BackgroundTask`)**, marked **temporary**.
  The extraction logic lives behind `MemoryService.extract_and_store`; when the Celery slice
  lands, only the trigger changes (`BackgroundTask(...)` → `task.delay(...)`).
- **Standalone "Память" screen**, not a Settings tab (the sidebar already lists «Память» as its
  own item). No settings rail in this slice.

## Backend

### Data & migration

- `pgvector` extension: migration runs `CREATE EXTENSION IF NOT EXISTS vector`.
- New `facts` table (new Alembic revision, chained on the latest head):
  - `id UUID PK`
  - `user_id UUID FK users(id) ON DELETE CASCADE`
  - `category` — enum `personal | project | preference`
  - `content TEXT`
  - `embedding VECTOR(768)` — `nomic-embed-text` dimensionality
  - `source` — enum `manual | auto`
  - `created_at` / `updated_at` (existing timestamp mixin)
  - Indexes: **HNSW** on `embedding` (`vector_cosine_ops`, `m=16`, `ef_construction=64`) +
    btree on `(user_id, created_at)`.
- `users.memory_auto_capture BOOLEAN NOT NULL DEFAULT true` (same migration or a chained one).
- `Fact` model in `db/models/fact.py` (pgvector's `Vector` SQLAlchemy type); `User` gains
  `memory_auto_capture: Mapped[bool]`.
- Config (`config.py`): `embedding_model: str = "nomic-embed-text"`, `memory_recall_k: int = 5`,
  `memory_recall_min_similarity: float = 0.3` (cosine; tunable), `memory_dedup_threshold: float = 0.9`.
- Docker: switch the Postgres image to `pgvector/pgvector:pg16` (compose + testcontainers) so the
  extension is available.

### Embeddings (provider abstraction)

- `BaseAgent.embed(texts: Sequence[str]) -> list[list[float]]` (abstract).
- `OllamaAgent.embed` calls Ollama `/api/embed` with `settings.embedding_model` (mockable via
  the existing `_client_factory` seam). Requires the model pulled in Ollama — document in README
  and surface in `/health` if cheap.
- Changing `embedding_model` implies re-embedding existing facts (documented limitation; v1 does
  not store per-row model provenance).

### Generic structured-output helper (for extraction)

- `BaseAgent.run_structured(model_name, system_prompt, user_content, output_type: type[T]) -> T`
  — a thin wrapper over a one-shot pydantic-ai `Agent(..., output_type=...)`. Generic; the memory
  service owns the extraction schema/prompt so the agent layer stays memory-agnostic.

### Generic tools seam + recall tool

- `BaseAgent.stream_reply(..., tools: Sequence[Tool] = ())` builds
  `Agent(self._build_model(model_name), tools=list(tools))`. `generate_title` is unchanged (no
  tools).
- The recall tool is a closure over the service (no pydantic-ai `deps` needed):
  ```python
  def make_recall_tool(memory_service, user_id):
      async def recall(query: str) -> str:
          """Search the user's long-term memory for relevant facts."""
          return format_facts(await memory_service.recall(user_id, query))
      return recall
  ```
- `ChatService.stream_turn` assembles the enabled tool list — `[make_recall_tool(...)]` in this
  slice — and passes it to `stream_reply`. Future tools (MCP/web/code) join the same list; the
  `stream_reply` signature does not change. A "tool registry / capability provider" can formalise
  assembly later; v1 assembles inline.
- System prompt for chat runs gains a nudge: *use `recall` when the question depends on personal
  or previously-shared context.*

### Retrieval — `MemoryService.recall`

- `recall(user_id, query) -> list[Fact]`: embed `query` via `BaseAgent.embed`, then
  `FactRepo.search(user_id, embedding, k=memory_recall_k)` — cosine (`<=>`) nearest, filtered by
  `memory_recall_min_similarity`. Returns facts (content + category) formatted for the tool.

### Auto-capture — `MemoryService.extract_and_store` (variant A)

- Trigger: the `POST /chats/{id}/messages` endpoint attaches
  `background=BackgroundTask(schedule_extraction, user_id, chat_id)` to its `StreamingResponse`.
  Starlette runs it after the response body is fully sent. `schedule_extraction` builds a
  **background-safe** `MemoryService` (its own session from the sessionmaker, not the
  request-scoped one) and calls `extract_and_store`, swallowing + logging all errors so they never
  surface to the client. (Regenerate does not auto-capture.)
- `extract_and_store(user_id, chat_id)`:
  1. If `user.memory_auto_capture` is off → no-op.
  2. Load the last user+assistant turn for `chat_id` from the DB (the assistant reply is already
     persisted by the time the stream's `done` fired — no text is threaded through the request).
  3. `run_structured(...)` — using the **chat's own model** (`chat.model`, loaded with the turn)
     — with an `ExtractedFacts` schema (`list[{content, category}]`) over that turn → candidate
     facts (may be empty).
  4. For each candidate: embed; `FactRepo.search` for the nearest existing fact; if similarity ≥
     `memory_dedup_threshold` → **skip** (v1); else insert with `source=auto`.
- Caveat (documented): if the process is killed mid-task, the last turn's capture is lost —
  acceptable for a convenience feature.

### API — `/memory` router

- `GET /memory/facts` → `list[FactOut]` (current user's facts, newest first).
- `POST /memory/facts` `{content, category}` → `FactOut` (embeds; `source=manual`).
- `PATCH /memory/facts/{id}` `{content?, category?}` → `FactOut` (re-embed iff `content` changed;
  at-least-one-field validator; ownership via a `get_owned_fact` dependency → 404).
- `DELETE /memory/facts/{id}` → `204`.
- `GET /memory/settings` → `{auto_capture: bool}`.
- `PATCH /memory/settings` `{auto_capture: bool}` → `{auto_capture}`.
- Schemas: `FactOut {id, category, content, source, created_at, updated_at}`,
  `FactCreate {content, category}`, `FactUpdate {content?, category?}`,
  `MemorySettingsOut/Update {auto_capture}`.

### Layering

`db/models/fact.py` → `repositories/fact_repo.py` (`list_by_user`, `create`, `get_owned`,
`update`, `delete`, `search(user_id, embedding, k)`) → `services/memory_service.py`
(add/list/update/delete/recall/extract_and_store/get+set auto_capture) → `api/routers/memory.py`
+ schemas. Embeddings + structured extraction go through the `agent/` layer. Reusable FastAPI
deps: `get_memory_service`, `get_owned_fact`.

## Frontend

### Navigation

- `ChatScreen` gains `view: 'chat' | 'memory'`. The sidebar «Память» item becomes an enabled
  button → `setView('memory')`, highlighted active like a chat; selecting a chat / «Новый чат»
  → `setView('chat')`. `<main>` renders `view === 'memory' ? <MemoryScreen/> : (welcome | active)`.
  `AssistantRuntimeProvider` stays wrapping (harmless; MemoryScreen ignores it).
- Sidebar props: `onOpenMemory` + `memoryActive`. «Память» loses `aria-disabled`. («Фоновые
  задачи», «Настройки» remain disabled placeholders.)
- *(A full `AppShell` extraction is deliberately deferred — it would force lifting all chat-list
  state out of `ChatScreen`; justified when the Settings shell arrives.)*

### Types & API

- Types: `Category = 'personal' | 'project' | 'preference'`,
  `FactOut {id, category, content, source, created_at, updated_at}`, `FactCreate`, `FactUpdate`,
  `MemorySettings {auto_capture}`.
- `chat/`-style module `memory/memoryApi.ts`: `listFacts`, `createFact`, `updateFact`,
  `deleteFact`, `getMemorySettings`, `patchMemorySettings`.
- `useFacts` hook: list + create/update/delete + toggle, **optimistic updates with reconcile-on-
  failure** (reuse the pattern from the chat-management work).

### Components

- `MemoryScreen`: header «Память» + «Авто-запоминание» toggle (accent) → `patchMemorySettings`;
  2-column fact-card grid (gap 12px); dashed «Добавить факт» → inline `FactForm` (content
  textarea + category select).
- `FactCard`: coloured category tag (map `Category` → colour), content, date, hover edit/delete;
  edit switches the card to an inline `FactForm`.
- Colours/spacing/radii per the design handoff tokens.

## Testing (TDD — tests first)

**Backend** (real Postgres via testcontainers on `pgvector/pgvector:pg16`, per-test tx isolation):
- `FactRepo.search` returns nearest facts in the right order (seed rows with known embeddings).
- `MemoryService.extract_and_store`: pydantic-ai `TestModel`/`FunctionModel` for extraction +
  a **stub embedder** injected through the provider seam (no real Ollama); asserts new facts
  inserted, near-duplicates skipped, and the `auto_capture=false` gate.
- `recall` tool inside a chat run: `TestModel` that calls `recall`; asserts seeded facts reach
  the model and the tool is registered via the generic `tools` list.
- API: facts CRUD (create embeds via stub, list, patch re-embeds on content change, delete),
  settings toggle, and **per-user isolation** (user A cannot see/mutate user B's facts).
- `OllamaAgent.embed`: mocked httpx transport (as with existing Ollama tests).

**Frontend** (Vitest + Testing Library + MSW on `/api/memory/*`):
- `MemoryScreen`: renders fact cards, add/edit/delete flows, auto-remember toggle.
- `useFacts`: optimistic update + rollback on failure.
- Sidebar «Память» navigation swaps `<main>` to `MemoryScreen` and highlights the item.

## Seams (future-facing)

- **retrieval** behind `MemoryService.recall` → add auto-injection or swap to mem0 without
  touching services/UI.
- **extraction** behind `MemoryService.extract_and_store` → Celery swap is a one-line trigger
  change.
- **embeddings** behind `BaseAgent.embed` → change model/provider centrally.
- **tools** behind `stream_reply(tools=…)` → MCP/web/code tools join the same list.

## Risks

- Small Ollama models may not reliably call the recall tool (chosen tradeoff) — mitigated by a
  system-prompt nudge; a function-calling-capable model is required for recall to fire.
- Variant A loses the last turn's capture if the process is killed mid-task (accepted).
- Changing the embedding model requires re-embedding existing facts (documented; no per-row model
  provenance in v1).
- pgvector must be present in the Postgres image (compose + testcontainers) — image change
  required.

## Success criteria

- User can add / edit / delete facts and toggle «Авто-запоминание» on the «Память» screen.
- The agent calls `recall` and answers using stored facts.
- With auto-capture on, facts are stored shortly after replies; near-duplicates are not
  duplicated; with it off, nothing is captured.
- Facts are strictly per-user isolated.
- `ruff` + `mypy` (backend) and `eslint` + `prettier` + `tsc` (frontend) clean; backend and
  frontend test suites green.
