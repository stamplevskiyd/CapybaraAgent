# Dual Agent Mode (Fast / Smart) — Design

**Date:** 2026-07-11
**Status:** approved for implementation planning

## Problem

The DeepAgents runtime plans steps, uses subagents, and orchestrates tools in a way weak
local models cannot follow — they get confused by the tooling and loop until the graph's
recursion limit trips (observed live: gemma4 hit 25 iterations with no answer). Simple
local models need a simpler execution path.

## Goal

Offer two per-thread agent modes, selectable in the composer:

- **Fast** (default) — a simple LLM + tool-calling loop for straightforward questions and
  edits; fewer reasoning steps, snappy, forgiving of weak models.
- **Smart** — the existing DeepAgents runtime for complex, multi-step tasks.

## Non-goals

- The composer's "Tools" menu (Python exec, web search, files, SQL, shell) — those tools
  do not exist in the backend yet; each is its own future slice. This slice ships only the
  fast/smart toggle.
- Restricting which tools a mode may use. Both modes expose the same per-user tools
  (recall + MCP); Fast simply calls them less by virtue of the simpler loop.
- Auto-selecting a mode from the prompt. The user picks it explicitly.

## Architecture

The mode is a second runtime behind the seams that already exist, not a parallel stack.

### Runtime: two graph factories, one runner

`create_react_agent` (langgraph.prebuilt) builds Fast; `create_deep_agent` builds Smart.
Both are LangGraph graphs, so `astream_events(version="v2")` emits the same
`on_chat_model_stream` / `on_tool_start` / `on_tool_end` events — `DeepAgentRunner`'s
event normalization, the checkpointer, and the per-turn `tool_provider` are reused
unchanged.

- New factory `build_fast_graph(registry, tools, *, model, checkpointer)` in
  `agent/deep_runtime.py`, mirroring `build_graph`. It calls `create_react_agent` with a
  simple system prompt and the same tool list.
- `build_graph` (Smart / DeepAgents) is unchanged.
- **Recursion cap:** `recursion_limit` is a LangGraph *run-config* key, not a build
  parameter, so the runner adds it to the per-turn config when `mode == "fast"` (a low
  value, 6). A confused weak model then returns a partial answer or fails fast instead of
  spinning; the existing `on_message` error handling (`cl.ErrorMessage`) surfaces a
  recursion overflow readably. Smart keeps LangGraph's default limit.

### Runner selects a factory per turn

`DeepAgentRunner.stream(content, *, model, thread_id, mode)` gains a `mode` argument. The
factory closure wired in `app.py` switches on it:

```python
def graph_factory(tools, model, mode):
    build = build_fast_graph if mode == "fast" else build_graph
    return build(model_registry, tools, model=model, checkpointer=checkpointer)
```

`GraphFactory`'s signature becomes `(tools, model, mode) -> EventStreamingGraph`. There is
still one runner and one `tool_provider`. `stream` also adds `recursion_limit` to the run
config for Fast (see Recursion cap above).

### Mode resolution mirrors model resolution

`chainlit_app.selected_mode(metadata, thread_id) -> Literal["fast", "smart"]`, mirroring
`selected_model`: the mode sent in the message metadata wins (the only channel before a new
thread has prefs), then the thread's saved `chat_pref.mode`, then the default `"fast"`.
`_pref_lookup` already returns the full `ChatPref` row, so `mode` is available with no new
lookup. `on_message` resolves both model and mode and passes them to `runner.stream`.

### Persistence: a `mode` column on `chat_prefs`

- **Model:** `ChatPref.mode: Mapped[str]` (default `"fast"`), a plain string column with a
  CHECK constraint `mode IN ('fast', 'smart')` (mirrors the fact-category pattern).
- **Migration:** a **new incremental Alembic revision** adds the column with
  `server_default='fast'`. (The earlier single-baseline collapse was a one-time reset; the
  app now runs against a live DB, so normal forward migrations resume. The live DB gets the
  column through this revision.)
- **API:** `ChatPrefUpsert` and `ChatPrefOut` gain `mode: Literal["fast", "smart"] = "fast"`.
- **Command:** `UpsertChatPref` gains a `mode` argument and writes it.

### Frontend: mirror the model plumbing exactly

The model selector's plumbing is the template; the mode toggle copies it.

- Composer (welcome + active) gets a mode pill next to the model selector: label
  (Быстрый/Умный), popover "Режим агента" with the two options and their descriptions from
  the design handoff. Default Fast.
- `ChatScreen` holds `agentMode` (draft) like `draftModel`, persisted to
  `localStorage`.
- The selected mode rides in each message's metadata alongside the model.
- On selecting a mode for an active thread, and on adopting a new thread's server id, PUT
  it to `/chat-prefs` (same call that already carries `is_favorite` + `model`).
- `useThreads` merges `mode` from `/chat-prefs` into each chat entry; `ChatOut`/`ChatPrefOut`
  TS types gain `mode`.

## Data flow (one turn)

1. User picks model + mode in the composer; both persist to draft + localStorage.
2. Message sent → `sendMessage` metadata carries `{ model, mode }`.
3. `on_message` → `selected_model` and `selected_mode` (metadata → chat_pref → default).
4. `runner.stream(text, model=…, thread_id=…, mode=…)` → factory builds the Fast or Smart
   graph → `astream_events` → normalized `RunnerEvent`s → Chainlit steps/tokens.
5. On new-thread adoption the frontend PUTs `{ is_favorite, model, mode }` to `/chat-prefs`.

## Error handling

- Fast recursion overflow → `GraphRecursionError` → caught by `on_message` → `cl.ErrorMessage`
  (existing path, no new handling).
- Unknown/invalid mode value → resolution falls back to `"fast"` (the default), never raises.
- Non-UUID thread id in `selected_mode` → same guard as `selected_model` (skip the pref
  lookup, use default).

## Testing

- `build_fast_graph` wiring: mirrors the `build_graph` test — asserts `create_react_agent`
  is handed the chat model, tools, checkpointer, and recursion config.
- Runner passes `mode` to the factory (extend the existing per-turn factory test).
- `selected_mode` resolution: mirrors `selected_model` tests (metadata wins, pref used,
  default fallback, non-UUID, unauthenticated).
- Migration test: `chat_prefs.mode` exists with the CHECK constraint after `upgrade head`.
- `UpsertChatPref` persists mode (extend the chat-pref command test).
- Frontend: composer renders the mode toggle and calls the handler; `useChainlitThread`
  send rides `mode` in metadata; `ChatScreen` persists mode on select and on adoption;
  `useThreads` merges mode.

## Success criteria

- A weak local model answers simple questions in Fast mode without hitting the recursion
  limit (the original blocker: dialog-memory smoke check becomes verifiable).
- Switching a thread to Smart uses the DeepAgents runtime.
- A thread remembers its mode across reload (persisted in `chat_prefs`), like its model.
- Backend and frontend tests pass; ruff + mypy strict clean.
