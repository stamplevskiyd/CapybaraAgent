# MCP client — backend core (sub-slice A) — design

**Date:** 2026-07-06
**Status:** Approved design, pending implementation plan
**Slice:** MCP client, sub-slice A — attach remote (HTTP/SSE) MCP servers, discover and
curate their tools, expose the enabled ones to the chat agent.

## Context

CapybaraAgent already streams tool calls end-to-end: the `recall` memory tool is a
`pydantic_ai.Tool[None]` built per-turn and passed to
`BaseAgent.stream_reply(tools=…)`; its invocation flows through
`StreamedToolCall`/`StreamedToolResult` → SSE `ToolCall`/`ToolResult` → the frontend
`ToolCallCard`. MCP is the next headline "agent" capability, and it plugs into exactly
this seam, so an MCP tool call renders through the existing path with **no UI changes**.

MCP is large (config + lifecycle + transport + discovery + curation + settings UI +
connect wizard + agent self-attach). It is therefore decomposed into sub-slices; this
spec covers **only sub-slice A (backend core)**.

**Decomposition (for reference, not this slice):**
- **A — MCP backend core (this spec).**
- **B — MCP settings UI:** «MCP-серверы» screen + connect-wizard (design handoff §5b /
  §6a / §6b) on top of A's API, including per-tool curation toggles.
- **C — advanced:** stdio transport, agent self-attaches a server from chat, health/status
  polling.

## Problem

There is no way to attach an external MCP tool server, so the agent is limited to its
built-in tools. A real driving use case: a user's **Home Assistant** MCP server exposes a
large tool catalog; a local model gets confused by long, undifferentiated tool lists, so
the user must be able to **curate which tools** are exposed, not just connect.

## Goal

Let a user attach a **remote (HTTP/SSE)** MCP server, have its tools discovered and
persisted, **enable/disable individual tools** (curation), and have the enabled tools
offered to the chat agent so the model can call them mid-turn — surfaced through the
existing tool-call streaming UI.

## Non-goals (sub-slice A)

- **Frontend / connect-wizard** — that is sub-slice B.
- **stdio (subprocess) transport** — remote HTTP/SSE only this slice; stdio is sub-slice C.
- **Agent self-attaching a server from chat** ("агент может подключить сервер сам") — C.
- **Encryption of stored auth headers at rest** — see Security & known limitations; this
  is an explicit **TODO for a dedicated follow-up slice**.
- **Health / status polling** of attached servers — status is captured at attach/refresh
  only.
- **Persistent connection pool** — connections are opened per-turn, not held open.

## Key decisions (from brainstorming)

1. **Remote transport only** (HTTP/SSE). No subprocess spawning inside the container —
   simpler and safer as the first slice.
2. **Per-turn connection + cached tool metadata.** The MCP session is opened only during
   `attach`, `refresh`, and each chat turn (then closed). Tool metadata is persisted at
   attach so the UI can show "N tools" without a live connection.
3. **Arbitrary auth headers.** A server config carries a key→value map of HTTP headers
   (covering `Authorization: Bearer …`, `X-Api-Key`, etc.). Bearer is just a special case.
4. **Per-tool curation is first-class**, not deferred. Every discovered tool has an
   `enabled` flag; the agent is only ever offered enabled tools of enabled servers. This
   directly serves the Home Assistant use case.
5. **Maximum reuse.** MCP tools are exposed to the agent via a new `toolsets=` parameter on
   `stream_reply`, using pydantic-ai's native MCP client. Their calls flow through the
   existing `StreamedToolCall`/`ToolResult`/`ToolCallCard` path unchanged.
6. **Per-user scoping.** Servers are scoped to `user_id` (FK to `users`, mirroring
   `facts`), forward-compatible with device-local profiles.
7. **Fail-open at turn time, loud on explicit actions.** A server unreachable *during a
   turn* is skipped (its tools drop out, logged) and the chat never breaks — matching the
   memory slice's "loud but non-fatal" ethos. `attach`/`refresh` are explicit user actions,
   so their failures surface as actionable errors.
8. **Secrets stored as plain JSON — encryption is a TODO** (see below). Recorded as a known
   limitation so it is not silently forgotten.

## Data model (Alembic migration)

**`mcp_servers`**

| Column             | Type          | Notes                                            |
| ------------------ | ------------- | ------------------------------------------------ |
| `id`               | UUID PK       |                                                  |
| `user_id`          | UUID FK users | per-user, like `facts`                           |
| `name`             | str           | display name / slug source                       |
| `url`              | str           | remote MCP endpoint (HTTP/SSE)                   |
| `headers`          | JSON          | key→value HTTP headers (**auth lives here**)     |
| `enabled`          | bool          | server-level on/off (default true)               |
| `last_connected_at`| datetime null | set on successful attach/refresh                 |
| `last_error`       | str null      | last attach/refresh error, for status            |
| `created_at`/`updated_at` | datetime | via existing timestamp mixin                    |

**`mcp_tools`**

| Column         | Type            | Notes                                          |
| -------------- | --------------- | ---------------------------------------------- |
| `id`           | UUID PK         |                                                |
| `server_id`    | UUID FK, cascade| delete tools when server is deleted            |
| `name`         | str             | tool name as reported by the server            |
| `description`  | str null        | passed through to the model as-is              |
| `input_schema` | JSON null       | JSON Schema reported by the server             |
| `enabled`      | bool            | **curation flag**, default true                |
| `created_at`/`updated_at` | datetime |                                              |

Unique constraint on `(server_id, name)`.

## Layers

Follows the project's `api → services → repositories → db` layering.

- **`McpServerRepo` / `McpToolRepo`** — all DB access (repository pattern; no ad-hoc
  queries elsewhere).
- **`McpService`**
  - `attach(user_id, name, url, headers)` — open an MCP session (pydantic-ai native
    HTTP/SSE client), handshake + `tools/list`, persist the server and its tools, set
    `last_connected_at`. Session closed after. On failure **persist nothing** (no partial
    server row) and raise an actionable error.
  - `refresh(server_id)` — re-open the session, re-sync the tool list, **preserving each
    tool's `enabled` flag by name**; newly-appeared tools default to `enabled=true`;
    tools no longer reported are removed.
  - `build_toolsets(user_id)` — return the agent-ready MCP toolset(s) covering **only
    enabled tools of enabled servers**, implemented via a pydantic-ai MCP toolset filtered
    to the enabled tool names. Returns empty when the user has no usable servers.
  - **Tool naming:** tools are exposed to the model under a namespaced name
    `{server_slug}__{tool}` to avoid collisions between servers and with the built-in
    `recall`; the original name is used for the actual MCP call.

## Chat integration

- Extend `BaseAgent.stream_reply` with a `toolsets: Sequence[...] = ()` parameter
  (alongside the existing `tools=…`), threaded into the pydantic-ai `Agent(..., toolsets=)`.
- `ChatService` appends `McpService.build_toolsets(user_id)` to the per-turn agent setup,
  next to the existing `recall` tool.
- MCP tool calls then stream through the existing
  `StreamedToolCall`/`StreamedToolResult` → SSE → `ToolCallCard` path — **no frontend
  change**.
- Turn-time fail-open: if building/using a server's session fails during the turn, its
  tools are omitted and the failure logged; the reply proceeds.

## API — `/api/mcp`

Uses reusable FastAPI dependencies (session, current user, repos, `McpService`).

| Method & path                                   | Purpose                                             |
| ----------------------------------------------- | --------------------------------------------------- |
| `GET  /mcp/servers`                             | list the user's servers with their tools/counts     |
| `POST /mcp/servers`                             | attach: validate connection, persist server + tools |
| `GET  /mcp/servers/{id}`                        | server detail incl. tools                           |
| `PATCH /mcp/servers/{id}`                       | update name / url / headers / enabled               |
| `DELETE /mcp/servers/{id}`                      | delete server (cascade tools)                       |
| `POST /mcp/servers/{id}/refresh`               | re-run discovery, preserving enabled flags          |
| `PATCH /mcp/servers/{id}/tools/{tool_id}`       | toggle a tool's `enabled` (curation)                |

**Error mapping (attach/refresh):** server unreachable → 502-style; server answered but
the config is bad (bad URL, auth rejected, not an MCP endpoint) → 4xx — actionable
messages in the style of the memory slice's 502/503.

## Error handling

- **Explicit actions** (`attach`, `refresh`): loud, actionable errors. `attach` persists
  nothing on failure; `refresh` records `last_error` on the existing server row.
- **Turn time**: fail-open — skip the unreachable server's tools, log, never break the
  reply. Explicit UI surfacing of turn-time MCP failures is deferred (later slice).

## Security & known limitations

- **Turn-time fail-open is preflight-based; the preflight→run race is not covered in
  sub-slice A.** `build_toolsets` opens a reachability check (`discover`) at the *start*
  of each turn; a server that fails this preflight is skipped so the reply proceeds. A
  server that *passes* the preflight but becomes unreachable *between* the preflight
  ``discover`` and the pydantic-ai agent's actual tool invocation is **not** masked — the
  error propagates through `stream_reply` and breaks the reply. Airtight run-time
  degradation (e.g. per-call retry, persistent connection pool) is deferred to the future
  connection-pool slice.
- **Auth headers are stored as plain JSON — NOT encrypted at rest. This is a TODO for a
  dedicated follow-up slice.** Rationale for deferring: CapybaraAgent is local-first (the
  DB lives on the user's own machine), and encryption brings key management/rotation that
  would bloat this slice. But tokens (e.g. a Home Assistant long-lived access token) are
  real secrets, so **at-rest encryption of `mcp_servers.headers` must be implemented before
  this is considered production-hardened.** Tracked as an explicit limitation, mirroring
  how the memory slice recorded "no per-row model provenance".
- Namespaced tool names prevent collision-based confusion/shadowing of the built-in tools.
- MCP tool output is model-facing untrusted content, same trust posture as any external
  tool result; no additional injection boundary is added in this slice beyond what the
  existing tool-result rendering provides.

## Testing (TDD)

- **Repos / service / API** against a real Postgres (testcontainers, per-test
  transactional isolation) — as elsewhere in the project.
- **MCP server is mocked** — a fake in-process MCP endpoint (or a mocked pydantic-ai MCP
  client) so tests never reach a real external server. Cover: attach persists server +
  tools; refresh preserves `enabled` flags and adds/removes tools; `build_toolsets`
  returns only enabled tools of enabled servers; tool namespacing.
- **Chat integration** via pydantic-ai `FunctionModel`/`TestModel`: the model
  deterministically "calls" an MCP tool and the test asserts the call/result stream through
  the existing SSE events.
- Error paths: unreachable server on attach (actionable error), unreachable server at turn
  time (fail-open, reply still completes).

## Out of scope confirmation

No frontend, no wizard, no stdio, no self-attach, no encryption, no health polling — those
are sub-slices B/C and dedicated follow-ups.
