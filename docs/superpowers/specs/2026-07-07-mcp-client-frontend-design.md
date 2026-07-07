# MCP client — frontend (sub-slice B) design

**Date:** 2026-07-07
**Status:** approved (brainstorming)
**Depends on:** MCP client backend core (sub-slice A, merged in PR #4)

## Summary

Add a frontend surface for managing MCP servers: a standalone "MCP-серверы" screen
reachable from the sidebar (mirroring the existing "Память" screen), plus a modal
connect-wizard for attaching a new HTTP MCP server. Users can view attached servers and
their discovered tools, enable/disable servers and individual tools, re-run discovery
(refresh), and remove servers.

This slice consumes the already-shipped backend `/mcp` API. No backend changes.

## Scope

**In scope**

- Standalone `McpScreen` reached from a new sidebar nav item (same integration pattern as
  Memory: a `view` value in `ChatScreen`, toggled from `Sidebar`).
- Modal connect-wizard, **HTTP-only**: fields `Название` (name), `URL`, and an optional
  key/value **headers editor** (auth headers; write-only). Steps: `form → checking →
  success | error`.
- Server cards: status dot, name, `url` (mono), enable/disable toggle, refresh button,
  delete (with confirm), tool count, tool chips with per-tool enable toggle.
- Info banner: "Агент может подключить сервер и сам — попросите его в чате."
- Empty state (no servers) and loading state.

**Out of scope (deferred)**

- Unified Settings rail (LLM / MCP / Память / Задачи) from the design handoff — Memory
  today is a standalone screen; MCP mirrors that. Consolidation is a later slice.
- Editing an existing server's `name`/`url` (re-attaching is the workaround).
- LLM-provider wizard, background-tasks UI.
- `stdio` transport — the backend supports HTTP remote servers only.
- Header encryption at rest (a known backend follow-up).

## Backend contract (already shipped)

Router prefix `/mcp`, all under the current (seeded local) user.

| Method & path | Purpose | Body → Response |
| --- | --- | --- |
| `GET /mcp/servers` | list servers with tools | → `McpServerOut[]` |
| `POST /mcp/servers` | attach + discover (synchronous) | `McpServerCreate` → `201 McpServerOut` |
| `GET /mcp/servers/{id}` | one server | → `McpServerOut` |
| `PATCH /mcp/servers/{id}` | update (we use `enabled`) | `McpServerUpdate` → `McpServerOut` |
| `DELETE /mcp/servers/{id}` | remove | → `204` |
| `POST /mcp/servers/{id}/refresh` | re-run discovery | → `McpServerOut` |
| `PATCH /mcp/servers/{id}/tools/{toolId}` | toggle a tool | `McpToolUpdate` → `McpToolOut` |

Schemas (snake_case over the wire):

- `McpServerCreate`: `{ name: string, url: string, headers?: Record<string,string> }`
- `McpServerUpdate`: `{ name?, url?, headers?, enabled? }` (at least one field)
- `McpToolUpdate`: `{ enabled: boolean }`
- `McpToolOut`: `{ id, name, description | null, enabled }`
- `McpServerOut`: `{ id, name, url, enabled, last_connected_at | null, last_error | null,
  created_at, updated_at, tools: McpToolOut[] }` — **`headers` is never echoed back**
  (write-only secret).

**Connect errors** on `POST /mcp/servers`:

- `502 Bad Gateway` — server unreachable (upstream outage).
- `400 Bad Request` — protocol/handshake failure (bad config).
- Body is FastAPI `{ "detail": "<human-actionable message>" }`. The frontend `ApiError`
  already carries `(status, body)`; the wizard parses `detail` from the body for display.

## Architecture

Follows the established frontend feature pattern (`src/<feature>/` + `<feature>Api.ts`
over `ApiClient` + a `useX` hook; presentational components in `src/components/`; a screen
in `src/screens/`).

### Types — `src/api/types.ts`

Add `McpToolOut`, `McpServerOut`, `McpServerCreate` mirroring the backend snake_case
shapes above.

### API layer — `src/mcp/mcpApi.ts`

Thin functions over the shared `ApiClient`:

- `listServers(api)` → `GET /mcp/servers`
- `createServer(api, name, url, headers)` → `POST /mcp/servers`
- `deleteServer(api, id)` → `DELETE /mcp/servers/{id}`
- `refreshServer(api, id)` → `POST /mcp/servers/{id}/refresh`
- `setServerEnabled(api, id, enabled)` → `PATCH /mcp/servers/{id}`
- `setToolEnabled(api, serverId, toolId, enabled)` → `PATCH /mcp/servers/{id}/tools/{toolId}`

### Hook — `src/mcp/useMcpServers.ts`

Mirrors `useFacts`: `useState`-held list + optimistic mutations reconciled from the server
on failure (`reload`).

- State: `servers: McpServerOut[]`, `loading: boolean`.
- `reload()` — re-fetch the list.
- `connect(name, url, headers)` — calls `createServer`; on success prepends the returned
  server (with its tools) to the list and returns it; **rethrows on failure** so the
  wizard can render the error step. (Not optimistic — the wizard drives the flow.)
- `toggleServer(id, enabled)`, `removeServer(id)`, `toggleTool(serverId, toolId, enabled)`
  — optimistic local update; on failure `await reload()`.
- `refresh(id)` — calls `refreshServer`, replaces that server in the list; exposes a
  per-server pending flag so the card can show a spinner.

### Components — `src/components/`

- `McpServerCard.tsx` (+ `.module.css`) — one server:
  - Status dot: **success** when `last_connected_at` is set and `last_error` is null;
    **error** when `last_error` is set. Error text shown on the card.
  - Name, `url` in mono, enable/disable toggle (calls `toggleServer`).
  - Refresh button (spinner while pending) and delete button (opens confirm).
  - Tool count + tool chips.
- `McpToolChip.tsx` — a tool's name (mono) with an enable toggle (calls `toggleTool`);
  disabled tools are visually muted.
- `ConnectWizard.tsx` (+ `.module.css`) — modal overlay + card styled per the handoff
  (backdrop blur, click-outside closes when not mid-check). Local step state
  `form | checking | success | error`:
  - **form** — `Название`, `URL`, `HeadersEditor` (optional), «Отмена» / «Подключить».
  - **checking** — spinner + "Проверяем соединение…" while the POST is in flight.
  - **success** — check icon, "Сервер подключён", "Обнаружено N инструментов", tool chips,
    «Готово» (closes).
  - **error** — message from `detail` (502 → "Сервер недоступен", 400 → "Не удалось
    подключиться"), «Назад» (return to form with fields preserved) / «Повторить».
  - `HeadersEditor` — dynamic key/value rows with add/remove; emits a `Record<string,string>`
    (empty → omitted from the request).

### Screen — `src/screens/McpScreen.tsx` (+ `.module.css`)

- Header: title "MCP-серверы" + subtitle (server count, Russian pluralization like
  `MemoryScreen`).
- Info banner (accent) with the self-connect hint.
- «Подключить» button → opens `ConnectWizard`.
- Server list of `McpServerCard`; empty state when none; loading state during initial load.

### Navigation integration

- `ChatScreen`: widen `view` state to `'chat' | 'memory' | 'mcp'`; render `<McpScreen/>`
  when `view === 'mcp'`; pass `onOpenMcp={() => setView('mcp')}` and `mcpActive` to
  `Sidebar`.
- `Sidebar`: add an enabled nav item (lucide `Plug` or `Server` icon) beside «Память»,
  wired to `onOpenMcp`/`mcpActive`, following the existing Memory nav item markup.

## Error handling

- Card mutations (toggle/delete/refresh/tool-toggle): optimistic, `reload()` on failure so
  the UI never drifts from persisted state (same contract as `useFacts`).
- Wizard connect failures: surface `detail` from the `ApiError` body on the error step;
  «Повторить» re-submits, «Назад» returns to the form with entered values intact.
- Server-side `last_error` renders as a red status dot plus the error text on the card.

## Testing (TDD)

Vitest + MSW + Testing Library, test files colocated (matching existing conventions):

- `mcpApi` — request shapes for each endpoint.
- `useMcpServers` — load, optimistic mutation + reload-on-fail, `connect` success and
  rethrow-on-error (MSW handlers).
- `McpServerCard` — status dot logic, toggle, refresh spinner, delete confirm, tool chips.
- `McpToolChip` — toggle wiring, muted disabled state.
- `ConnectWizard` — all four steps, headers editor, 502/400 error mapping, retry/back.
- `McpScreen` — empty state, list render, opening the wizard.
- Navigation — sidebar MCP item highlights and switches `view` (extend the existing
  `ChatScreen`/`Sidebar` nav tests).

## Open questions

None blocking. The `stdio` transport and header encryption are explicitly deferred; the
unified Settings rail is a future consolidation slice.
