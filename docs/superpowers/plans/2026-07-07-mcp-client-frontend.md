# MCP Client Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a frontend for managing MCP servers — a standalone «MCP-серверы» screen (reached from the sidebar, mirroring «Память») plus a modal connect-wizard for attaching HTTP MCP servers — consuming the already-shipped `/mcp` backend API.

**Architecture:** Follows the established feature pattern: a `src/mcp/` folder (`mcpApi.ts` over the shared `ApiClient` + a `useMcpServers` hook holding state in `useState` with optimistic mutations reconciled from the server on failure), presentational components in `src/components/`, and a screen in `src/screens/` wired into `ChatScreen`'s `view` switch and the `Sidebar` nav.

**Tech Stack:** React 18 + TypeScript + Vite, CSS Modules, lucide-react icons, Vitest + MSW + Testing Library.

## Global Constraints

- **Language:** TypeScript, strict; no new runtime dependencies (use existing `ApiClient`, `lucide-react`).
- **Transport:** HTTP MCP servers only — no `stdio` UI. Wizard fields are name + url + optional headers.
- **Secrets:** `headers` are write-only — sent on create, never rendered (backend never echoes them).
- **Wire format:** snake_case field names exactly as the backend returns (`last_connected_at`, `last_error`, `created_at`, `updated_at`).
- **UI copy:** Russian, matching existing screens (e.g. «Память»).
- **Quality gates (run before every commit):** `npm run lint`, `npm run typecheck`, `npm run test` — all from `frontend/`.
- **Node:** 20+ (`frontend/.nvmrc`); run all `npm` commands from `frontend/`.
- **Test style:** MSW handlers hit `/api/<path>`; seed a session with
  `localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'r' }))` in `beforeEach`; wrap hooks/screens in `<AuthProvider>`. Import `{ server, http, HttpResponse }` from `../test/msw`.
- **Backend contract:** `GET/POST /mcp/servers`, `GET/PATCH/DELETE /mcp/servers/{id}`, `POST /mcp/servers/{id}/refresh`, `PATCH /mcp/servers/{id}/tools/{toolId}`. `POST` performs synchronous discovery: `201` with the server (+ tools), `502` if unreachable, `400` on protocol/handshake failure; error body is `{ "detail": "<message>" }`.

---

## File Structure

- `src/api/types.ts` — **modify**: add `McpToolOut`, `McpServerOut`, `McpServerCreate`.
- `src/mcp/mcpApi.ts` — **create**: API calls over `ApiClient`.
- `src/mcp/useMcpServers.ts` — **create**: state hook (load + optimistic mutations + `connect`).
- `src/components/McpToolChip.tsx` (+ `.module.css`) — **create**: one tool chip with enable toggle.
- `src/components/McpServerCard.tsx` (+ `.module.css`) — **create**: one server card (status, toggle, refresh, delete, tool chips).
- `src/components/ConnectWizard.tsx` (+ `.module.css`) — **create**: modal wizard (form → checking → success | error) incl. an inline headers editor.
- `src/components/plural.ts` — **modify**: add `pluralServers`.
- `src/screens/McpScreen.tsx` (+ `.module.css`) — **create**: banner + connect button + server list + empty/loading states.
- `src/screens/ChatScreen.tsx` — **modify**: widen `view` to include `'mcp'`, render `<McpScreen/>`, pass sidebar props.
- `src/components/Sidebar.tsx` — **modify**: add MCP nav item + `onOpenMcp`/`mcpActive` props.

---

## Task 1: Types + API layer

**Files:**
- Modify: `frontend/src/api/types.ts`
- Create: `frontend/src/mcp/mcpApi.ts`
- Test: `frontend/src/mcp/mcpApi.test.ts`

**Interfaces:**
- Consumes: `ApiClient` from `../api/client` (`get`/`post`/`patch`/`del`).
- Produces:
  - Types `McpToolOut { id, name, description: string | null, enabled }`, `McpServerOut { id, name, url, enabled, last_connected_at: string | null, last_error: string | null, created_at, updated_at, tools: McpToolOut[] }`, `McpServerCreate { name, url, headers?: Record<string,string> }`.
  - `listServers(api): Promise<McpServerOut[]>`, `createServer(api, name, url, headers): Promise<McpServerOut>`, `deleteServer(api, id): Promise<void>`, `refreshServer(api, id): Promise<McpServerOut>`, `setServerEnabled(api, id, enabled): Promise<McpServerOut>`, `setToolEnabled(api, serverId, toolId, enabled): Promise<McpToolOut>`.

- [ ] **Step 1: Add types** — append to `frontend/src/api/types.ts`:

```ts
export interface McpToolOut {
  id: string
  name: string
  description: string | null
  enabled: boolean
}

export interface McpServerOut {
  id: string
  name: string
  url: string
  enabled: boolean
  last_connected_at: string | null
  last_error: string | null
  created_at: string
  updated_at: string
  tools: McpToolOut[]
}

export interface McpServerCreate {
  name: string
  url: string
  headers?: Record<string, string>
}
```

- [ ] **Step 2: Write the failing test** — `frontend/src/mcp/mcpApi.test.ts`:

```ts
import { server, http, HttpResponse } from '../test/msw'
import { createApiClient } from '../api/client'
import {
  createServer,
  deleteServer,
  listServers,
  refreshServer,
  setServerEnabled,
  setToolEnabled,
} from './mcpApi'

const api = createApiClient({ getToken: () => 't', onUnauthorized: () => {} })

const srv = {
  id: 's1',
  name: 'github',
  url: 'https://mcp.example/github',
  enabled: true,
  last_connected_at: '2026-07-07T10:00:00Z',
  last_error: null,
  created_at: '2026-07-07T10:00:00Z',
  updated_at: '2026-07-07T10:00:00Z',
  tools: [{ id: 't1', name: 'search', description: null, enabled: true }],
}

test('listServers GETs /mcp/servers', async () => {
  server.use(http.get('/api/mcp/servers', () => HttpResponse.json([srv])))
  expect((await listServers(api))[0].name).toBe('github')
})

test('createServer POSTs name/url/headers', async () => {
  let body: unknown
  server.use(
    http.post('/api/mcp/servers', async ({ request }) => {
      body = await request.json()
      return HttpResponse.json(srv, { status: 201 })
    }),
  )
  await createServer(api, 'github', 'https://mcp.example/github', { Authorization: 'Bearer x' })
  expect(body).toEqual({
    name: 'github',
    url: 'https://mcp.example/github',
    headers: { Authorization: 'Bearer x' },
  })
})

test('setServerEnabled PATCHes enabled', async () => {
  let body: unknown
  server.use(
    http.patch('/api/mcp/servers/s1', async ({ request }) => {
      body = await request.json()
      return HttpResponse.json({ ...srv, enabled: false })
    }),
  )
  await setServerEnabled(api, 's1', false)
  expect(body).toEqual({ enabled: false })
})

test('setToolEnabled PATCHes the tool', async () => {
  server.use(
    http.patch('/api/mcp/servers/s1/tools/t1', () =>
      HttpResponse.json({ id: 't1', name: 'search', description: null, enabled: false }),
    ),
  )
  expect((await setToolEnabled(api, 's1', 't1', false)).enabled).toBe(false)
})

test('refreshServer POSTs /refresh and deleteServer DELETEs', async () => {
  server.use(
    http.post('/api/mcp/servers/s1/refresh', () => HttpResponse.json(srv)),
    http.delete('/api/mcp/servers/s1', () => new HttpResponse(null, { status: 204 })),
  )
  expect((await refreshServer(api, 's1')).id).toBe('s1')
  await expect(deleteServer(api, 's1')).resolves.toBeUndefined()
})
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npm run test -- src/mcp/mcpApi.test.ts`
Expected: FAIL — cannot resolve `./mcpApi`.

- [ ] **Step 4: Write minimal implementation** — `frontend/src/mcp/mcpApi.ts`:

```ts
/** MCP server API calls over the shared authenticated ApiClient. */
import type { ApiClient } from '../api/client'
import type { McpServerOut, McpToolOut } from '../api/types'

export const listServers = (api: ApiClient) => api.get<McpServerOut[]>('/mcp/servers')

export const createServer = (
  api: ApiClient,
  name: string,
  url: string,
  headers: Record<string, string>,
) => api.post<McpServerOut>('/mcp/servers', { name, url, headers })

export const deleteServer = (api: ApiClient, id: string) => api.del(`/mcp/servers/${id}`)

export const refreshServer = (api: ApiClient, id: string) =>
  api.post<McpServerOut>(`/mcp/servers/${id}/refresh`)

export const setServerEnabled = (api: ApiClient, id: string, enabled: boolean) =>
  api.patch<McpServerOut>(`/mcp/servers/${id}`, { enabled })

export const setToolEnabled = (
  api: ApiClient,
  serverId: string,
  toolId: string,
  enabled: boolean,
) => api.patch<McpToolOut>(`/mcp/servers/${serverId}/tools/${toolId}`, { enabled })
```

- [ ] **Step 5: Run tests + gates to verify they pass**

Run: `cd frontend && npm run test -- src/mcp/mcpApi.test.ts && npm run typecheck && npm run lint`
Expected: PASS; typecheck + lint clean.

- [ ] **Step 6: Commit**

```bash
git add src/api/types.ts src/mcp/mcpApi.ts src/mcp/mcpApi.test.ts
git commit -m "feat(mcp-fe): MCP types and API layer"
```

---

## Task 2: `useMcpServers` hook

**Files:**
- Create: `frontend/src/mcp/useMcpServers.ts`
- Test: `frontend/src/mcp/useMcpServers.test.tsx`

**Interfaces:**
- Consumes: `useApiClient` from `../auth/AuthContext`; the `mcpApi` functions from Task 1; `McpServerOut` type.
- Produces: `useMcpServers()` returning `{ servers: McpServerOut[], loading: boolean, reload(): Promise<void>, connect(name, url, headers): Promise<McpServerOut>, toggleServer(id, enabled): Promise<void>, removeServer(id): Promise<void>, refresh(id): Promise<void>, toggleTool(serverId, toolId, enabled): Promise<void> }`. `connect` prepends the created server and **rethrows on failure**; the other mutations are optimistic and call `reload()` on failure.

- [ ] **Step 1: Write the failing test** — `frontend/src/mcp/useMcpServers.test.tsx`:

```tsx
import { renderHook, waitFor, act } from '@testing-library/react'
import { server, http, HttpResponse } from '../test/msw'
import { AuthProvider } from '../auth/AuthContext'
import { useMcpServers } from './useMcpServers'

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <AuthProvider>{children}</AuthProvider>
)

beforeEach(() =>
  localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'r' })),
)

const srv = {
  id: 's1',
  name: 'github',
  url: 'https://mcp.example/github',
  enabled: true,
  last_connected_at: '2026-07-07T10:00:00Z',
  last_error: null,
  created_at: '2026-07-07T10:00:00Z',
  updated_at: '2026-07-07T10:00:00Z',
  tools: [{ id: 't1', name: 'search', description: null, enabled: true }],
}

test('loads servers on mount', async () => {
  server.use(http.get('/api/mcp/servers', () => HttpResponse.json([srv])))
  const { result } = renderHook(() => useMcpServers(), { wrapper })
  await waitFor(() => expect(result.current.loading).toBe(false))
  expect(result.current.servers[0].name).toBe('github')
})

test('connect prepends the created server', async () => {
  const created = { ...srv, id: 's2', name: 'fs' }
  server.use(
    http.get('/api/mcp/servers', () => HttpResponse.json([srv])),
    http.post('/api/mcp/servers', () => HttpResponse.json(created, { status: 201 })),
  )
  const { result } = renderHook(() => useMcpServers(), { wrapper })
  await waitFor(() => expect(result.current.loading).toBe(false))
  await act(async () => {
    await result.current.connect('fs', 'https://mcp.example/fs', {})
  })
  expect(result.current.servers[0].id).toBe('s2')
})

test('connect rethrows on failure', async () => {
  server.use(
    http.get('/api/mcp/servers', () => HttpResponse.json([])),
    http.post('/api/mcp/servers', () =>
      HttpResponse.json({ detail: 'unreachable' }, { status: 502 }),
    ),
  )
  const { result } = renderHook(() => useMcpServers(), { wrapper })
  await waitFor(() => expect(result.current.loading).toBe(false))
  await expect(
    act(async () => {
      await result.current.connect('x', 'https://x', {})
    }),
  ).rejects.toBeTruthy()
})

test('toggleServer rolls back on failure', async () => {
  let calls = 0
  server.use(
    http.get('/api/mcp/servers', () => {
      calls += 1
      return HttpResponse.json([srv]) // reload returns enabled:true again
    }),
    http.patch('/api/mcp/servers/s1', () => new HttpResponse(null, { status: 500 })),
  )
  const { result } = renderHook(() => useMcpServers(), { wrapper })
  await waitFor(() => expect(result.current.loading).toBe(false))
  await act(async () => {
    await result.current.toggleServer('s1', false)
  })
  await waitFor(() => expect(result.current.servers[0].enabled).toBe(true))
  expect(calls).toBeGreaterThan(1) // reload happened
})

test('toggleTool flips a tool optimistically', async () => {
  server.use(
    http.get('/api/mcp/servers', () => HttpResponse.json([srv])),
    http.patch('/api/mcp/servers/s1/tools/t1', () =>
      HttpResponse.json({ id: 't1', name: 'search', description: null, enabled: false }),
    ),
  )
  const { result } = renderHook(() => useMcpServers(), { wrapper })
  await waitFor(() => expect(result.current.loading).toBe(false))
  await act(async () => {
    await result.current.toggleTool('s1', 't1', false)
  })
  expect(result.current.servers[0].tools[0].enabled).toBe(false)
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- src/mcp/useMcpServers.test.tsx`
Expected: FAIL — cannot resolve `./useMcpServers`.

- [ ] **Step 3: Write minimal implementation** — `frontend/src/mcp/useMcpServers.ts`:

```ts
/** MCP servers state with optimistic mutations reconciled from the server on failure. */
import { useCallback, useEffect, useState } from 'react'
import { useApiClient } from '../auth/AuthContext'
import type { McpServerOut } from '../api/types'
import {
  createServer,
  deleteServer,
  listServers,
  refreshServer,
  setServerEnabled,
  setToolEnabled,
} from './mcpApi'

/**
 * Load and mutate the current user's MCP servers.
 *
 * Card mutations update local state optimistically; on failure the list is
 * re-synced from the server via `reload`. `connect` is wizard-driven: it prepends
 * the created server and rethrows on failure so the wizard can show its error step.
 */
export function useMcpServers() {
  const api = useApiClient()
  const [servers, setServers] = useState<McpServerOut[]>([])
  const [loading, setLoading] = useState(true)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      setServers(await listServers(api))
    } finally {
      setLoading(false)
    }
  }, [api])

  useEffect(() => {
    void reload()
  }, [reload])

  const connect = useCallback(
    async (name: string, url: string, headers: Record<string, string>) => {
      const created = await createServer(api, name, url, headers)
      setServers((prev) => [created, ...prev])
      return created
    },
    [api],
  )

  const toggleServer = useCallback(
    async (id: string, enabled: boolean) => {
      setServers((prev) => prev.map((s) => (s.id === id ? { ...s, enabled } : s)))
      try {
        const updated = await setServerEnabled(api, id, enabled)
        setServers((prev) => prev.map((s) => (s.id === id ? updated : s)))
      } catch {
        await reload()
      }
    },
    [api, reload],
  )

  const removeServer = useCallback(
    async (id: string) => {
      setServers((prev) => prev.filter((s) => s.id !== id))
      try {
        await deleteServer(api, id)
      } catch {
        await reload()
      }
    },
    [api, reload],
  )

  const refresh = useCallback(
    async (id: string) => {
      try {
        const updated = await refreshServer(api, id)
        setServers((prev) => prev.map((s) => (s.id === id ? updated : s)))
      } catch {
        await reload()
      }
    },
    [api, reload],
  )

  const toggleTool = useCallback(
    async (serverId: string, toolId: string, enabled: boolean) => {
      setServers((prev) =>
        prev.map((s) =>
          s.id === serverId
            ? { ...s, tools: s.tools.map((t) => (t.id === toolId ? { ...t, enabled } : t)) }
            : s,
        ),
      )
      try {
        await setToolEnabled(api, serverId, toolId, enabled)
      } catch {
        await reload()
      }
    },
    [api, reload],
  )

  return { servers, loading, reload, connect, toggleServer, removeServer, refresh, toggleTool }
}
```

- [ ] **Step 4: Run tests + gates to verify they pass**

Run: `cd frontend && npm run test -- src/mcp/useMcpServers.test.tsx && npm run typecheck && npm run lint`
Expected: PASS; gates clean.

- [ ] **Step 5: Commit**

```bash
git add src/mcp/useMcpServers.ts src/mcp/useMcpServers.test.tsx
git commit -m "feat(mcp-fe): useMcpServers hook with optimistic mutations"
```

---

## Task 3: `McpToolChip` component

**Files:**
- Create: `frontend/src/components/McpToolChip.tsx`
- Create: `frontend/src/components/McpToolChip.module.css`
- Test: `frontend/src/components/McpToolChip.test.tsx`

**Interfaces:**
- Consumes: `McpToolOut` type.
- Produces: `<McpToolChip tool={McpToolOut} onToggle={(enabled: boolean) => void} />`. Renders a checkbox labelled `Инструмент <name>`; muted when disabled; shows `description` as the `title` tooltip.

- [ ] **Step 1: Write the failing test** — `frontend/src/components/McpToolChip.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { McpToolChip } from './McpToolChip'
import type { McpToolOut } from '../api/types'

const tool: McpToolOut = { id: 't1', name: 'search', description: 'Search repos', enabled: true }

test('renders the tool name and fires onToggle', async () => {
  const onToggle = vi.fn()
  render(<McpToolChip tool={tool} onToggle={onToggle} />)
  const cb = screen.getByRole('checkbox', { name: 'Инструмент search' })
  expect(cb).toBeChecked()
  expect(screen.getByText('search')).toBeInTheDocument()
  await userEvent.click(cb)
  expect(onToggle).toHaveBeenCalledWith(false)
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- src/components/McpToolChip.test.tsx`
Expected: FAIL — cannot resolve `./McpToolChip`.

- [ ] **Step 3: Write implementation** — `frontend/src/components/McpToolChip.tsx`:

```tsx
/** A discovered MCP tool: mono name with an enable/disable checkbox toggle. */
import type { McpToolOut } from '../api/types'
import styles from './McpToolChip.module.css'

export function McpToolChip({
  tool,
  onToggle,
}: {
  tool: McpToolOut
  onToggle: (enabled: boolean) => void
}) {
  return (
    <label
      className={tool.enabled ? styles.chip : `${styles.chip} ${styles.disabled}`}
      title={tool.description ?? undefined}
    >
      <input
        type="checkbox"
        className={styles.toggle}
        checked={tool.enabled}
        onChange={(e) => onToggle(e.target.checked)}
        aria-label={`Инструмент ${tool.name}`}
      />
      {tool.name}
    </label>
  )
}
```

And `frontend/src/components/McpToolChip.module.css`:

```css
.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 9px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11.5px;
  color: var(--text-secondary);
  cursor: pointer;
}

.disabled {
  opacity: 0.45;
}

.toggle {
  width: 12px;
  height: 12px;
  accent-color: var(--accent);
  cursor: pointer;
}
```

- [ ] **Step 4: Run tests + gates to verify they pass**

Run: `cd frontend && npm run test -- src/components/McpToolChip.test.tsx && npm run typecheck && npm run lint`
Expected: PASS; gates clean.

- [ ] **Step 5: Commit**

```bash
git add src/components/McpToolChip.tsx src/components/McpToolChip.module.css src/components/McpToolChip.test.tsx
git commit -m "feat(mcp-fe): McpToolChip with enable toggle"
```

---

## Task 4: `McpServerCard` component

**Files:**
- Create: `frontend/src/components/McpServerCard.tsx`
- Create: `frontend/src/components/McpServerCard.module.css`
- Test: `frontend/src/components/McpServerCard.test.tsx`

**Interfaces:**
- Consumes: `McpServerOut` type; `McpToolChip` (Task 3).
- Produces: `<McpServerCard server={McpServerOut} onToggle={(enabled: boolean) => void} onRefresh={() => Promise<void>} onDelete={() => void} onToggleTool={(toolId: string, enabled: boolean) => void} />`. Status dot is `success` when `last_connected_at` is set and `last_error` is null, else `error`; `last_error` text is shown. Refresh button holds a local pending flag (spinner). Delete button asks a native `confirm` before calling `onDelete`.

- [ ] **Step 1: Write the failing test** — `frontend/src/components/McpServerCard.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { McpServerCard } from './McpServerCard'
import type { McpServerOut } from '../api/types'

const server: McpServerOut = {
  id: 's1',
  name: 'github',
  url: 'https://mcp.example/github',
  enabled: true,
  last_connected_at: '2026-07-07T10:00:00Z',
  last_error: null,
  created_at: '2026-07-07T10:00:00Z',
  updated_at: '2026-07-07T10:00:00Z',
  tools: [{ id: 't1', name: 'search', description: null, enabled: true }],
}

function noop() {}

test('renders name, url, tool count and fires toggle', async () => {
  const onToggle = vi.fn()
  render(
    <McpServerCard
      server={server}
      onToggle={onToggle}
      onRefresh={async () => {}}
      onDelete={noop}
      onToggleTool={noop}
    />,
  )
  expect(screen.getByText('github')).toBeInTheDocument()
  expect(screen.getByText('https://mcp.example/github')).toBeInTheDocument()
  expect(screen.getByText(/1 инструмент/)).toBeInTheDocument()

  await userEvent.click(screen.getByRole('checkbox', { name: 'Сервер включён' }))
  expect(onToggle).toHaveBeenCalledWith(false)
})

test('shows the error text when last_error is set', () => {
  render(
    <McpServerCard
      server={{ ...server, last_error: 'boom', last_connected_at: null }}
      onToggle={noop}
      onRefresh={async () => {}}
      onDelete={noop}
      onToggleTool={noop}
    />,
  )
  expect(screen.getByText('boom')).toBeInTheDocument()
})

test('confirms before deleting', async () => {
  const onDelete = vi.fn()
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  render(
    <McpServerCard
      server={server}
      onToggle={noop}
      onRefresh={async () => {}}
      onDelete={onDelete}
      onToggleTool={noop}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: 'Удалить сервер' }))
  expect(onDelete).toHaveBeenCalled()
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- src/components/McpServerCard.test.tsx`
Expected: FAIL — cannot resolve `./McpServerCard`.

- [ ] **Step 3: Write implementation** — `frontend/src/components/McpServerCard.tsx`:

```tsx
/** One attached MCP server: status, url, enable toggle, refresh/delete, tool chips. */
import { useState } from 'react'
import { RotateCw, Trash2 } from 'lucide-react'
import type { McpServerOut } from '../api/types'
import { McpToolChip } from './McpToolChip'
import styles from './McpServerCard.module.css'

/** Russian plural for «инструмент»: 1 → инструмент, 2–4 → инструмента, else → инструментов. */
function pluralTools(n: number): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return 'инструмент'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'инструмента'
  return 'инструментов'
}

export function McpServerCard({
  server,
  onToggle,
  onRefresh,
  onDelete,
  onToggleTool,
}: {
  server: McpServerOut
  onToggle: (enabled: boolean) => void
  onRefresh: () => Promise<void>
  onDelete: () => void
  onToggleTool: (toolId: string, enabled: boolean) => void
}) {
  const [refreshing, setRefreshing] = useState(false)
  const ok = server.last_connected_at !== null && server.last_error === null

  async function handleRefresh() {
    setRefreshing(true)
    try {
      await onRefresh()
    } finally {
      setRefreshing(false)
    }
  }

  function handleDelete() {
    if (window.confirm(`Удалить сервер «${server.name}»?`)) onDelete()
  }

  return (
    <div className={styles.card}>
      <div className={styles.head}>
        <span
          className={ok ? `${styles.dot} ${styles.dotOk}` : `${styles.dot} ${styles.dotErr}`}
          aria-hidden="true"
        />
        <div className={styles.titleBlock}>
          <span className={styles.name}>{server.name}</span>
          <span className={styles.url}>{server.url}</span>
        </div>
        <div className={styles.actions}>
          <label className={styles.switch} aria-label="Сервер включён">
            <input
              type="checkbox"
              checked={server.enabled}
              onChange={(e) => onToggle(e.target.checked)}
            />
          </label>
          <button
            type="button"
            className={styles.iconBtn}
            aria-label="Обновить"
            disabled={refreshing}
            onClick={handleRefresh}
          >
            <RotateCw size={14} className={refreshing ? styles.spin : undefined} />
          </button>
          <button
            type="button"
            className={styles.iconBtn}
            aria-label="Удалить сервер"
            onClick={handleDelete}
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {server.last_error && <div className={styles.error}>{server.last_error}</div>}

      <div className={styles.toolCount}>
        {server.tools.length} {pluralTools(server.tools.length)}
      </div>
      <div className={styles.tools}>
        {server.tools.map((t) => (
          <McpToolChip
            key={t.id}
            tool={t}
            onToggle={(enabled) => onToggleTool(t.id, enabled)}
          />
        ))}
      </div>
    </div>
  )
}
```

And `frontend/src/components/McpServerCard.module.css`:

```css
.card {
  border: 1px solid rgba(255, 255, 255, 0.09);
  background: rgba(255, 255, 255, 0.03);
  border-radius: 16px;
  padding: 18px 20px;
}

.head {
  display: flex;
  align-items: center;
  gap: 12px;
}

.dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex-shrink: 0;
}

.dotOk {
  background: var(--success);
  box-shadow: 0 0 0 4px rgba(111, 191, 142, 0.16);
}

.dotErr {
  background: var(--error);
  box-shadow: 0 0 0 4px rgba(224, 138, 122, 0.16);
}

.titleBlock {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.name {
  font-size: 14.5px;
  color: var(--text-primary);
  font-weight: 500;
}

.url {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11.5px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.switch input {
  accent-color: var(--accent);
  cursor: pointer;
}

.iconBtn {
  display: inline-flex;
  padding: 5px;
  border: none;
  background: transparent;
  border-radius: 7px;
  color: var(--text-muted);
  cursor: pointer;
}

.iconBtn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.07);
  color: var(--text-secondary);
}

.iconBtn:disabled {
  opacity: 0.5;
  cursor: default;
}

.spin {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.error {
  margin-top: 10px;
  font-size: 12.5px;
  color: var(--error);
}

.toolCount {
  margin-top: 14px;
  font-size: 11px;
  color: var(--text-faint);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.tools {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
```

- [ ] **Step 4: Run tests + gates to verify they pass**

Run: `cd frontend && npm run test -- src/components/McpServerCard.test.tsx && npm run typecheck && npm run lint`
Expected: PASS; gates clean.

- [ ] **Step 5: Commit**

```bash
git add src/components/McpServerCard.tsx src/components/McpServerCard.module.css src/components/McpServerCard.test.tsx
git commit -m "feat(mcp-fe): McpServerCard with status, toggle, refresh, delete"
```

---

## Task 5: `ConnectWizard` modal (with inline headers editor)

**Files:**
- Create: `frontend/src/components/ConnectWizard.tsx`
- Create: `frontend/src/components/ConnectWizard.module.css`
- Test: `frontend/src/components/ConnectWizard.test.tsx`

**Interfaces:**
- Consumes: `McpServerOut` type; `ApiError` from `../api/client`; `McpToolChip` is **not** used here (success step renders plain read-only chips).
- Produces: `<ConnectWizard onConnect={(name, url, headers) => Promise<McpServerOut>} onClose={() => void} />`. Internal step machine `form | checking | success | error`. On submit it calls `onConnect`; success → shows discovered tool names + «Готово» (calls `onClose`); failure → error step showing the parsed `detail` (falls back to `502 → «Сервер недоступен»`, else «Не удалось подключиться»), with «Назад» (return to form, fields preserved) and «Повторить». The overlay backdrop closes the modal only when not in the `checking` step.

- [ ] **Step 1: Write the failing test** — `frontend/src/components/ConnectWizard.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConnectWizard } from './ConnectWizard'
import { ApiError } from '../api/client'
import type { McpServerOut } from '../api/types'

const created: McpServerOut = {
  id: 's1',
  name: 'github',
  url: 'https://mcp.example/github',
  enabled: true,
  last_connected_at: '2026-07-07T10:00:00Z',
  last_error: null,
  created_at: '2026-07-07T10:00:00Z',
  updated_at: '2026-07-07T10:00:00Z',
  tools: [{ id: 't1', name: 'search', description: null, enabled: true }],
}

test('submits name/url and shows the success step with tools', async () => {
  const onConnect = vi.fn().mockResolvedValue(created)
  const onClose = vi.fn()
  render(<ConnectWizard onConnect={onConnect} onClose={onClose} />)

  await userEvent.type(screen.getByLabelText('Название'), 'github')
  await userEvent.type(screen.getByLabelText('URL'), 'https://mcp.example/github')
  await userEvent.click(screen.getByRole('button', { name: 'Подключить' }))

  expect(onConnect).toHaveBeenCalledWith('github', 'https://mcp.example/github', {})
  expect(await screen.findByText('Сервер подключён')).toBeInTheDocument()
  expect(screen.getByText('search')).toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: 'Готово' }))
  expect(onClose).toHaveBeenCalled()
})

test('adds a header row and includes it in the request', async () => {
  const onConnect = vi.fn().mockResolvedValue(created)
  render(<ConnectWizard onConnect={onConnect} onClose={() => {}} />)

  await userEvent.type(screen.getByLabelText('Название'), 'github')
  await userEvent.type(screen.getByLabelText('URL'), 'https://x')
  await userEvent.click(screen.getByRole('button', { name: 'Добавить заголовок' }))
  await userEvent.type(screen.getByLabelText('Ключ заголовка 1'), 'Authorization')
  await userEvent.type(screen.getByLabelText('Значение заголовка 1'), 'Bearer x')
  await userEvent.click(screen.getByRole('button', { name: 'Подключить' }))

  expect(onConnect).toHaveBeenCalledWith('github', 'https://x', { Authorization: 'Bearer x' })
})

test('shows the error detail and allows going back', async () => {
  const onConnect = vi
    .fn()
    .mockRejectedValue(new ApiError(400, JSON.stringify({ detail: 'bad handshake' })))
  render(<ConnectWizard onConnect={onConnect} onClose={() => {}} />)

  await userEvent.type(screen.getByLabelText('Название'), 'x')
  await userEvent.type(screen.getByLabelText('URL'), 'https://x')
  await userEvent.click(screen.getByRole('button', { name: 'Подключить' }))

  expect(await screen.findByText('bad handshake')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Назад' }))
  expect(screen.getByLabelText('Название')).toHaveValue('x')
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- src/components/ConnectWizard.test.tsx`
Expected: FAIL — cannot resolve `./ConnectWizard`.

- [ ] **Step 3: Write implementation** — `frontend/src/components/ConnectWizard.tsx`:

```tsx
/** Modal wizard to attach an HTTP MCP server: form → checking → success | error. */
import { useState } from 'react'
import { Plug, Plus, X } from 'lucide-react'
import { ApiError } from '../api/client'
import type { McpServerOut } from '../api/types'
import styles from './ConnectWizard.module.css'

type Step = 'form' | 'checking' | 'success' | 'error'
interface HeaderRow {
  key: string
  value: string
}

/** Extract a human message from a failed connect attempt. */
function errorDetail(err: unknown): string {
  if (err instanceof ApiError) {
    try {
      const body = JSON.parse(err.message) as { detail?: string }
      if (body.detail) return body.detail
    } catch {
      // non-JSON body — fall through to status-based copy
    }
    if (err.status === 502) return 'Сервер недоступен'
  }
  return 'Не удалось подключиться'
}

function rowsToRecord(rows: HeaderRow[]): Record<string, string> {
  const out: Record<string, string> = {}
  for (const r of rows) {
    const k = r.key.trim()
    if (k) out[k] = r.value
  }
  return out
}

export function ConnectWizard({
  onConnect,
  onClose,
}: {
  onConnect: (name: string, url: string, headers: Record<string, string>) => Promise<McpServerOut>
  onClose: () => void
}) {
  const [step, setStep] = useState<Step>('form')
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [rows, setRows] = useState<HeaderRow[]>([])
  const [result, setResult] = useState<McpServerOut | null>(null)
  const [error, setError] = useState('')

  const canSubmit = name.trim() !== '' && url.trim() !== ''

  async function submit() {
    setStep('checking')
    try {
      const server = await onConnect(name.trim(), url.trim(), rowsToRecord(rows))
      setResult(server)
      setStep('success')
    } catch (err) {
      setError(errorDetail(err))
      setStep('error')
    }
  }

  function setRow(i: number, patch: Partial<HeaderRow>) {
    setRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))
  }

  return (
    <div
      className={styles.overlay}
      onClick={() => {
        if (step !== 'checking') onClose()
      }}
    >
      <div className={styles.card} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <span className={styles.headerIcon}>
            <Plug size={16} />
          </span>
          <div className={styles.headerText}>
            <span className={styles.title}>Подключение MCP-сервера</span>
            <span className={styles.subtitle}>Локально · ключи не покидают устройство</span>
          </div>
          <button type="button" className={styles.close} aria-label="Закрыть" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        {step === 'form' && (
          <div className={styles.body}>
            <label className={styles.field}>
              Название
              <input
                className={styles.input}
                aria-label="Название"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="github"
              />
            </label>
            <label className={styles.field}>
              URL
              <input
                className={`${styles.input} ${styles.mono}`}
                aria-label="URL"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://mcp.example/github"
              />
            </label>

            <div className={styles.headersBlock}>
              <span className={styles.caption}>Заголовки (опционально)</span>
              {rows.map((r, i) => (
                <div className={styles.headerRow} key={i}>
                  <input
                    className={`${styles.input} ${styles.mono}`}
                    aria-label={`Ключ заголовка ${i + 1}`}
                    value={r.key}
                    onChange={(e) => setRow(i, { key: e.target.value })}
                    placeholder="Authorization"
                  />
                  <input
                    className={`${styles.input} ${styles.mono}`}
                    aria-label={`Значение заголовка ${i + 1}`}
                    value={r.value}
                    onChange={(e) => setRow(i, { value: e.target.value })}
                    placeholder="Bearer …"
                  />
                  <button
                    type="button"
                    className={styles.iconBtn}
                    aria-label={`Удалить заголовок ${i + 1}`}
                    onClick={() => setRows((prev) => prev.filter((_, idx) => idx !== i))}
                  >
                    <X size={14} />
                  </button>
                </div>
              ))}
              <button
                type="button"
                className={styles.addHeader}
                onClick={() => setRows((prev) => [...prev, { key: '', value: '' }])}
              >
                <Plus size={13} /> Добавить заголовок
              </button>
            </div>

            <div className={styles.info}>
              Агент может подключить сервер и сам — попросите его в чате.
            </div>

            <div className={styles.footer}>
              <button type="button" className={styles.cancel} onClick={onClose}>
                Отмена
              </button>
              <button
                type="button"
                className={styles.primary}
                disabled={!canSubmit}
                onClick={submit}
              >
                Подключить
              </button>
            </div>
          </div>
        )}

        {step === 'checking' && (
          <div className={styles.centered}>
            <div className={styles.spinner} />
            <span className={styles.title}>Проверяем соединение…</span>
          </div>
        )}

        {step === 'success' && result && (
          <div className={styles.body}>
            <div className={styles.centered}>
              <div className={styles.successIcon}>✓</div>
              <span className={styles.title}>Сервер подключён</span>
              <span className={styles.subtitle}>Обнаружено {result.tools.length}</span>
            </div>
            <div className={styles.chips}>
              {result.tools.map((t) => (
                <span className={styles.chip} key={t.id}>
                  {t.name}
                </span>
              ))}
            </div>
            <div className={styles.footer}>
              <button type="button" className={styles.primary} onClick={onClose}>
                Готово
              </button>
            </div>
          </div>
        )}

        {step === 'error' && (
          <div className={styles.body}>
            <div className={styles.centered}>
              <div className={styles.errorIcon}>!</div>
              <span className={styles.title}>Не удалось подключиться</span>
              <span className={styles.errorText}>{error}</span>
            </div>
            <div className={styles.footer}>
              <button type="button" className={styles.cancel} onClick={() => setStep('form')}>
                Назад
              </button>
              <button type="button" className={styles.primary} onClick={submit}>
                Повторить
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
```

And `frontend/src/components/ConnectWizard.module.css`:

```css
.overlay {
  position: absolute;
  inset: 0;
  z-index: 24;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.card {
  width: 100%;
  max-width: 520px;
  max-height: 84vh;
  overflow: auto;
  background: rgba(26, 23, 20, 0.92);
  backdrop-filter: blur(40px);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 20px;
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.6);
}

.header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px 22px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.headerIcon {
  display: inline-flex;
  padding: 8px;
  border-radius: 10px;
  background: rgba(216, 155, 108, 0.16);
  color: var(--accent);
}

.headerText {
  display: flex;
  flex-direction: column;
  flex: 1;
}

.title {
  font-size: 16px;
  color: var(--text-primary);
}

.subtitle {
  font-size: 12.5px;
  color: var(--text-muted);
}

.close {
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}

.body {
  padding: 20px 22px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12.5px;
  color: var(--text-muted);
}

.input {
  padding: 9px 11px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 10px;
  background: rgba(0, 0, 0, 0.22);
  color: var(--text-primary);
  font-size: 13.5px;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12.5px;
}

.headersBlock {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.caption {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-faint);
}

.headerRow {
  display: grid;
  grid-template-columns: 1fr 1fr auto;
  gap: 6px;
  align-items: center;
}

.iconBtn {
  display: inline-flex;
  padding: 6px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  border-radius: 7px;
  cursor: pointer;
}

.iconBtn:hover {
  background: rgba(255, 255, 255, 0.07);
}

.addHeader {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  align-self: flex-start;
  border: 1px dashed rgba(255, 255, 255, 0.18);
  background: transparent;
  color: var(--text-secondary);
  border-radius: 9px;
  padding: 6px 10px;
  font-size: 12.5px;
  cursor: pointer;
}

.info {
  border: 1px solid rgba(216, 155, 108, 0.42);
  background: rgba(216, 155, 108, 0.14);
  color: var(--text-secondary);
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 12.5px;
}

.footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.cancel {
  padding: 9px 16px;
  border: 1px solid rgba(255, 255, 255, 0.18);
  background: transparent;
  color: var(--text-secondary);
  border-radius: 10px;
  cursor: pointer;
}

.primary {
  padding: 9px 18px;
  border: none;
  background: var(--accent);
  color: #241a12;
  border-radius: 10px;
  font-weight: 500;
  cursor: pointer;
}

.primary:disabled {
  opacity: 0.5;
  cursor: default;
}

.centered {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 22px 0;
  text-align: center;
}

.spinner {
  width: 38px;
  height: 38px;
  border: 3px solid rgba(255, 255, 255, 0.14);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.successIcon,
.errorIcon {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
}

.successIcon {
  background: rgba(111, 191, 142, 0.16);
  color: var(--success);
}

.errorIcon {
  background: rgba(224, 138, 122, 0.16);
  color: var(--error);
}

.errorText {
  font-size: 12.5px;
  color: var(--error);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.chip {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11.5px;
  color: var(--text-secondary);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 8px;
  padding: 3px 9px;
}
```

- [ ] **Step 4: Run tests + gates to verify they pass**

Run: `cd frontend && npm run test -- src/components/ConnectWizard.test.tsx && npm run typecheck && npm run lint`
Expected: PASS; gates clean.

- [ ] **Step 5: Commit**

```bash
git add src/components/ConnectWizard.tsx src/components/ConnectWizard.module.css src/components/ConnectWizard.test.tsx
git commit -m "feat(mcp-fe): ConnectWizard modal with headers editor and error step"
```

---

## Task 6: `McpScreen`

**Files:**
- Create: `frontend/src/screens/McpScreen.tsx`
- Create: `frontend/src/screens/McpScreen.module.css`
- Modify: `frontend/src/components/plural.ts` (add `pluralServers`)
- Test: `frontend/src/screens/McpScreen.test.tsx`
- Test: `frontend/src/components/plural.test.ts` (add `pluralServers` cases)

**Interfaces:**
- Consumes: `useMcpServers` (Task 2), `McpServerCard` (Task 4), `ConnectWizard` (Task 5), `pluralServers`.
- Produces: `<McpScreen />` — self-contained screen; opens `ConnectWizard` from the «Подключить» button and wires its `onConnect` to the hook's `connect`.

- [ ] **Step 1: Add `pluralServers` + its failing test** — append to `frontend/src/components/plural.ts`:

```ts
/** Returns the Russian plural form of «сервер» for a count. */
export function pluralServers(n: number): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return 'сервер'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'сервера'
  return 'серверов'
}
```

Append to `frontend/src/components/plural.test.ts`:

```ts
import { pluralServers } from './plural'

test('pluralServers', () => {
  expect(pluralServers(1)).toBe('сервер')
  expect(pluralServers(3)).toBe('сервера')
  expect(pluralServers(5)).toBe('серверов')
  expect(pluralServers(11)).toBe('серверов')
})
```

- [ ] **Step 2: Write the failing screen test** — `frontend/src/screens/McpScreen.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, http, HttpResponse } from '../test/msw'
import { AuthProvider } from '../auth/AuthContext'
import { McpScreen } from './McpScreen'

beforeEach(() =>
  localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'r' })),
)

const srv = {
  id: 's1',
  name: 'github',
  url: 'https://mcp.example/github',
  enabled: true,
  last_connected_at: '2026-07-07T10:00:00Z',
  last_error: null,
  created_at: '2026-07-07T10:00:00Z',
  updated_at: '2026-07-07T10:00:00Z',
  tools: [{ id: 't1', name: 'search', description: null, enabled: true }],
}

function renderScreen() {
  return render(
    <AuthProvider>
      <McpScreen />
    </AuthProvider>,
  )
}

test('shows the empty state when there are no servers', async () => {
  server.use(http.get('/api/mcp/servers', () => HttpResponse.json([])))
  renderScreen()
  expect(await screen.findByText(/Пока нет подключённых серверов/)).toBeInTheDocument()
})

test('lists servers and opens the connect wizard', async () => {
  server.use(http.get('/api/mcp/servers', () => HttpResponse.json([srv])))
  renderScreen()
  expect(await screen.findByText('github')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Подключить' }))
  expect(screen.getByText('Подключение MCP-сервера')).toBeInTheDocument()
})
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && npm run test -- src/screens/McpScreen.test.tsx src/components/plural.test.ts`
Expected: FAIL — cannot resolve `./McpScreen`; `pluralServers` undefined.

- [ ] **Step 4: Write implementation** — `frontend/src/screens/McpScreen.tsx`:

```tsx
/** Standalone «MCP-серверы» screen: info banner, connect wizard, and server cards. */
import { useState } from 'react'
import { Plug } from 'lucide-react'
import { McpServerCard } from '../components/McpServerCard'
import { ConnectWizard } from '../components/ConnectWizard'
import { pluralServers } from '../components/plural'
import { useMcpServers } from '../mcp/useMcpServers'
import styles from './McpScreen.module.css'

export function McpScreen() {
  const { servers, loading, connect, toggleServer, removeServer, refresh, toggleTool } =
    useMcpServers()
  const [wizardOpen, setWizardOpen] = useState(false)

  return (
    <div className={styles.screen}>
      <div className={styles.inner}>
        <div className={styles.header}>
          <div>
            <h2 className={styles.title}>MCP-серверы</h2>
            <p className={styles.subtitle}>
              {servers.length} {pluralServers(servers.length)} подключено.
            </p>
          </div>
          <button type="button" className={styles.connectBtn} onClick={() => setWizardOpen(true)}>
            <Plug size={15} /> Подключить
          </button>
        </div>

        <div className={styles.banner}>
          Агент может подключать серверы сам — попросите его в чате.
        </div>

        {loading ? (
          <p className={styles.muted}>Загрузка…</p>
        ) : servers.length === 0 ? (
          <p className={styles.muted}>Пока нет подключённых серверов.</p>
        ) : (
          <div className={styles.list}>
            {servers.map((s) => (
              <McpServerCard
                key={s.id}
                server={s}
                onToggle={(enabled) => void toggleServer(s.id, enabled)}
                onRefresh={() => refresh(s.id)}
                onDelete={() => void removeServer(s.id)}
                onToggleTool={(toolId, enabled) => void toggleTool(s.id, toolId, enabled)}
              />
            ))}
          </div>
        )}
      </div>

      {wizardOpen && (
        <ConnectWizard onConnect={connect} onClose={() => setWizardOpen(false)} />
      )}
    </div>
  )
}
```

And `frontend/src/screens/McpScreen.module.css`:

```css
.screen {
  position: relative;
  height: 100%;
  overflow: auto;
}

.inner {
  max-width: 760px;
  margin: 0 auto;
  padding: 32px 34px;
}

.header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.title {
  font-size: 24px;
  letter-spacing: -0.5px;
  color: var(--text-primary);
  margin: 0;
}

.subtitle {
  font-size: 14px;
  color: var(--text-muted);
  margin: 4px 0 0;
}

.connectBtn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 9px 16px;
  border: none;
  background: var(--accent);
  color: #241a12;
  border-radius: 10px;
  font-weight: 500;
  cursor: pointer;
}

.banner {
  margin-top: 20px;
  border: 1px solid rgba(216, 155, 108, 0.42);
  background: rgba(216, 155, 108, 0.14);
  color: var(--text-secondary);
  border-radius: 12px;
  padding: 12px 14px;
  font-size: 13px;
}

.muted {
  margin-top: 24px;
  color: var(--text-muted);
  font-size: 14px;
}

.list {
  margin-top: 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
```

- [ ] **Step 5: Run tests + gates to verify they pass**

Run: `cd frontend && npm run test -- src/screens/McpScreen.test.tsx src/components/plural.test.ts && npm run typecheck && npm run lint`
Expected: PASS; gates clean.

- [ ] **Step 6: Commit**

```bash
git add src/screens/McpScreen.tsx src/screens/McpScreen.module.css src/components/plural.ts src/components/plural.test.ts src/screens/McpScreen.test.tsx
git commit -m "feat(mcp-fe): McpScreen with server list, banner, and wizard"
```

---

## Task 7: Navigation integration (Sidebar + ChatScreen)

**Files:**
- Modify: `frontend/src/components/Sidebar.tsx`
- Modify: `frontend/src/screens/ChatScreen.tsx`
- Test: `frontend/src/components/Sidebar.mcp.test.tsx`

**Interfaces:**
- Consumes: `McpScreen` (Task 6).
- Produces: `Sidebar` gains props `onOpenMcp: () => void` and `mcpActive: boolean`, rendering a nav button (lucide `Server` icon, label «MCP-серверы») above «Память». `ChatScreen`'s `view` union becomes `'chat' | 'memory' | 'mcp'` and renders `<McpScreen/>` when `view === 'mcp'`.

- [ ] **Step 1: Write the failing test** — `frontend/src/components/Sidebar.mcp.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AuthProvider } from '../auth/AuthContext'
import { Sidebar } from './Sidebar'

function noop() {}

function renderSidebar(overrides: Partial<Parameters<typeof Sidebar>[0]> = {}) {
  return render(
    <AuthProvider>
      <Sidebar
        chats={[]}
        activeChatId={null}
        collapsed={false}
        onToggleCollapse={noop}
        onSelect={noop}
        onNewChat={noop}
        onToggleFavorite={noop}
        onRename={noop}
        onDelete={noop}
        onOpenMemory={noop}
        memoryActive={false}
        onOpenMcp={noop}
        mcpActive={false}
        {...overrides}
      />
    </AuthProvider>,
  )
}

test('renders the MCP nav item and fires onOpenMcp', async () => {
  const onOpenMcp = vi.fn()
  renderSidebar({ onOpenMcp })
  await userEvent.click(screen.getByRole('button', { name: 'MCP-серверы' }))
  expect(onOpenMcp).toHaveBeenCalled()
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- src/components/Sidebar.mcp.test.tsx`
Expected: FAIL — `Sidebar` has no `onOpenMcp`/`mcpActive` props; no MCP button.

- [ ] **Step 3: Wire `Sidebar`** — in `frontend/src/components/Sidebar.tsx`:

Add `Server` to the lucide import (line 3):

```tsx
import { Plus, Search, Brain, Server, Clock, Settings, Star, PanelLeft } from 'lucide-react'
```

Add the two props to the destructuring (after `memoryActive` at ~line 46):

```tsx
  onOpenMemory,
  memoryActive,
  onOpenMcp,
  mcpActive,
```

Add their types to the props type block (after the `memoryActive: boolean` entry at ~line 62):

```tsx
  /** True when the «Память» screen is the active view (highlights the nav item). */
  memoryActive: boolean
  /** Open the standalone «MCP-серверы» screen. */
  onOpenMcp: () => void
  /** True when the «MCP-серверы» screen is the active view. */
  mcpActive: boolean
```

Add the nav button immediately before the «Память» button (inside `.bottomBlock`, before the `onOpenMemory` button at ~line 155):

```tsx
          <button
            type="button"
            className={
              mcpActive ? `${styles.navButton} ${styles.navButtonActive}` : styles.navButton
            }
            onClick={onOpenMcp}
          >
            <Server size={16} />
            MCP-серверы
          </button>
```

- [ ] **Step 4: Wire `ChatScreen`** — in `frontend/src/screens/ChatScreen.tsx`:

Add the import (next to the `MemoryScreen` import at ~line 9):

```tsx
import { McpScreen } from './McpScreen'
```

Widen the `view` state (line ~40):

```tsx
  const [view, setView] = useState<'chat' | 'memory' | 'mcp'>('chat')
```

Pass the new props to `<Sidebar>` (next to `onOpenMemory`/`memoryActive` at ~line 195):

```tsx
          onOpenMemory={() => setView('memory')}
          memoryActive={view === 'memory'}
          onOpenMcp={() => setView('mcp')}
          mcpActive={view === 'mcp'}
```

Render the screen — change the main-content branch (line ~209) from:

```tsx
          {view === 'memory' ? (
            <MemoryScreen />
          ) : activeChatId === null ? (
```

to:

```tsx
          {view === 'memory' ? (
            <MemoryScreen />
          ) : view === 'mcp' ? (
            <McpScreen />
          ) : activeChatId === null ? (
```

- [ ] **Step 5: Run tests + full gates to verify everything passes**

Run: `cd frontend && npm run test && npm run typecheck && npm run lint`
Expected: PASS — the new Sidebar test plus the whole suite; typecheck + lint clean.

- [ ] **Step 6: Commit**

```bash
git add src/components/Sidebar.tsx src/screens/ChatScreen.tsx src/components/Sidebar.mcp.test.tsx
git commit -m "feat(mcp-fe): wire MCP screen into sidebar nav and ChatScreen"
```

---

## Self-Review

**Spec coverage:**
- Standalone screen reached from sidebar → Tasks 6–7. ✓
- Modal connect-wizard, HTTP-only (name + url + optional headers), steps form/checking/success/error → Task 5. ✓
- Server cards: status dot, name, url, enable toggle, refresh, delete-with-confirm, tool count, tool chips + tool toggles → Tasks 3–4. ✓
- Info banner → Tasks 5 (wizard) + 6 (screen). ✓
- Empty + loading states → Task 6. ✓
- Optimistic mutations + reload-on-fail; `connect` rethrows → Task 2. ✓
- Error mapping 502/400 with `detail` → Task 5 (`errorDetail`). ✓
- Snake_case wire types; headers write-only → Task 1. ✓
- Testing per component/hook/screen/nav → every task. ✓
- Deferred (unified Settings rail, edit name/url, stdio, LLM wizard, header encryption) → not implemented, by design. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases"; every code step is complete. ✓

**Type consistency:** `McpServerOut`/`McpToolOut`/`McpServerCreate` defined in Task 1 and used verbatim thereafter. Hook API (`connect`, `toggleServer`, `removeServer`, `refresh`, `toggleTool`) defined in Task 2 and consumed identically in Task 6. `McpServerCard` prop names (`onToggle`, `onRefresh`, `onDelete`, `onToggleTool`) match between Task 4 and Task 6. `ConnectWizard` props (`onConnect`, `onClose`) match between Task 5 and Task 6. Sidebar props (`onOpenMcp`, `mcpActive`) match between Task 7 test, Sidebar, and ChatScreen. ✓
