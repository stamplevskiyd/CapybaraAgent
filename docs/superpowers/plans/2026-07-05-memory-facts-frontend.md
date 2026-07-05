# Memory (facts) — Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the standalone **«Память»** screen — a fact-card grid with add/edit/delete, an «Авто-запоминание» toggle, reached from the sidebar — wired to the `/memory` backend API with optimistic updates.

**Architecture:** Mirror the existing `chat/` slice: a thin `memory/memoryApi.ts` over the shared `ApiClient`, a `useFacts` hook (list + settings, optimistic mutate with reconcile-on-failure), presentational `FactCard`/`FactForm` components, and a `MemoryScreen` that composes them. Navigation is a `view: 'chat' | 'memory'` switch in `ChatScreen`; the sidebar «Память» item becomes an enabled button.

**Tech Stack:** Vite + React 18 + TypeScript, CSS Modules, lucide-react icons, Vitest + Testing Library + MSW. Node ≥ 20.

**Backend contract (already shipped on `main`):**
- `GET /memory/facts` → `FactOut[]` (newest first)
- `POST /memory/facts` `{content, category}` → `FactOut` (201)
- `PATCH /memory/facts/{id}` `{content?, category?}` → `FactOut`
- `DELETE /memory/facts/{id}` → 204
- `GET /memory/settings` → `{auto_capture: boolean}`
- `PATCH /memory/settings` `{auto_capture: boolean}` → `{auto_capture}`
- `FactOut = {id, category, content, source, created_at, updated_at}` where `category ∈ personal|project|preference`, `source ∈ manual|auto`.

**Spec:** `docs/superpowers/specs/2026-07-05-memory-facts-design.md` (Frontend section).

## Global Constraints

Every task's requirements implicitly include these:

- **Node ≥ 20.** The shell's default Node may be older and shell env does not persist between Bash calls. Run every frontend command **from the `frontend/` directory** with a modern Node on PATH, e.g. prefix with `PATH="$HOME/.nvm/versions/node/v22.23.1/bin:$PATH"` (known-good in this repo) or `source ~/.nvm/nvm.sh && nvm use 22`. All commands below assume you are in `frontend/`.
- **Gates (must pass):** `npm run lint` (eslint `--max-warnings 0`), `npm run typecheck` (`tsc --noEmit`), `npm run test` (vitest run). The final task also runs `npx prettier --check .` and `npm run build`.
- **Language: RU only** — all user-visible copy is Russian, consistent with the app. No i18n.
- **Types match the backend verbatim:** the fact field is **`content`** (not `text`); `category` is the union `'personal' | 'project' | 'preference'`; responses use snake_case (`created_at`, `auto_capture`).
- **API paths carry NO `/api` prefix in code** — `createApiClient` prepends `/api`. So call `'/memory/facts'`; MSW handlers mock `'/api/memory/facts'`.
- **Category colours (from the design handoff), exact:** personal `#D89B6C` / bg `rgba(216,155,108,0.14)` (label «Личное»); project `#7fa8d0` / bg `rgba(127,168,208,0.14)` (label «Проект»); preference `#8fbf9e` / bg `rgba(143,191,158,0.14)` (label «Предпочтения»).
- **Follow existing patterns:** CSS Modules co-located per component; hooks mirror `chat/useChats.ts`; api modules mirror `chat/chatApi.ts`; tests mirror `chat/useChats.test.tsx` (wrapper = `AuthProvider`; `beforeEach` seeds `localStorage 'capybara.session'`; MSW from `../test/msw`).
- **TDD:** failing test first, watch it fail, minimal implementation, watch it pass, commit.
- **Scoped staging:** `git add` only the files you touched — never `git add -A` (the user commits concurrently).

---

## File Structure

**New files:**
- `frontend/src/memory/categories.ts` — the `CATEGORIES` list + `CATEGORY_BY_VALUE` map (label/colour/bg), shared by `FactCard` and `FactForm`.
- `frontend/src/memory/memoryApi.ts` — `listFacts`, `createFact`, `updateFact`, `deleteFact`, `getMemorySettings`, `patchMemorySettings`.
- `frontend/src/memory/useFacts.ts` — the hook (facts + auto-capture, optimistic mutate + rollback).
- `frontend/src/memory/useFacts.test.tsx` — hook tests (MSW).
- `frontend/src/components/FactForm.tsx` + `FactForm.module.css` — inline add/edit form (content textarea + category select).
- `frontend/src/components/FactForm.test.tsx`
- `frontend/src/components/FactCard.tsx` + `FactCard.module.css` — coloured tag + content + date + hover edit/delete.
- `frontend/src/components/FactCard.test.tsx`
- `frontend/src/screens/MemoryScreen.tsx` + `MemoryScreen.module.css` — header + toggle + grid + add-fact.
- `frontend/src/screens/MemoryScreen.test.tsx`
- `frontend/src/screens/MemoryNav.test.tsx` — sidebar→view-switch integration test.

**Modified files:**
- `frontend/src/api/types.ts` — add `Category`, `FactOut`, `FactCreate`, `FactUpdate`, `MemorySettings`.
- `frontend/src/components/Sidebar.tsx` + `Sidebar.module.css` — «Память» becomes an enabled button; `onOpenMemory` + `memoryActive` props.
- `frontend/src/screens/ChatScreen.tsx` — `view` state + wiring + render `MemoryScreen`.

---

## Task 1: Types, API module, and the `useFacts` hook

**Files:**
- Modify: `frontend/src/api/types.ts`
- Create: `frontend/src/memory/categories.ts`
- Create: `frontend/src/memory/memoryApi.ts`
- Create: `frontend/src/memory/useFacts.ts`
- Test: `frontend/src/memory/useFacts.test.tsx`

**Interfaces:**
- Produces types: `Category = 'personal' | 'project' | 'preference'`; `FactOut {id, category: Category, content, source: 'manual' | 'auto', created_at, updated_at}`; `FactCreate {content, category}`; `FactUpdate {content?, category?}`; `MemorySettings {auto_capture}`.
- Produces `memoryApi`: `listFacts(api)`, `createFact(api, content, category)`, `updateFact(api, id, patch: FactUpdate)`, `deleteFact(api, id)`, `getMemorySettings(api)`, `patchMemorySettings(api, autoCapture: boolean)`.
- Produces `useFacts()` returning `{ facts: FactOut[], autoCapture: boolean, loading: boolean, reload, addFact(content, category) => Promise<FactOut>, editFact(id, patch) => Promise<void>, removeFact(id) => Promise<void>, toggleAutoCapture(value) => Promise<void> }`.

- [ ] **Step 1: Add the types** — append to `frontend/src/api/types.ts`:

```typescript
export type Category = 'personal' | 'project' | 'preference'

export interface FactOut {
  id: string
  category: Category
  content: string
  source: 'manual' | 'auto'
  created_at: string
  updated_at: string
}

export interface FactCreate {
  content: string
  category: Category
}

export interface FactUpdate {
  content?: string
  category?: Category
}

export interface MemorySettings {
  auto_capture: boolean
}
```

- [ ] **Step 2: Add the category metadata** — create `frontend/src/memory/categories.ts`:

```typescript
/** Fixed fact categories with their RU labels and design-handoff colours. */
import type { Category } from '../api/types'

export interface CategoryMeta {
  value: Category
  label: string
  color: string
  bg: string
}

export const CATEGORIES: CategoryMeta[] = [
  { value: 'personal', label: 'Личное', color: '#D89B6C', bg: 'rgba(216,155,108,0.14)' },
  { value: 'project', label: 'Проект', color: '#7fa8d0', bg: 'rgba(127,168,208,0.14)' },
  { value: 'preference', label: 'Предпочтения', color: '#8fbf9e', bg: 'rgba(143,191,158,0.14)' },
]

export const CATEGORY_BY_VALUE: Record<Category, CategoryMeta> = Object.fromEntries(
  CATEGORIES.map((c) => [c.value, c]),
) as Record<Category, CategoryMeta>
```

- [ ] **Step 3: Add the API module** — create `frontend/src/memory/memoryApi.ts`:

```typescript
/** Memory (facts) API calls over the shared authenticated ApiClient. */
import type { ApiClient } from '../api/client'
import type { Category, FactOut, FactUpdate, MemorySettings } from '../api/types'

export const listFacts = (api: ApiClient) => api.get<FactOut[]>('/memory/facts')

export const createFact = (api: ApiClient, content: string, category: Category) =>
  api.post<FactOut>('/memory/facts', { content, category })

export const updateFact = (api: ApiClient, id: string, patch: FactUpdate) =>
  api.patch<FactOut>(`/memory/facts/${id}`, patch)

export const deleteFact = (api: ApiClient, id: string) => api.del(`/memory/facts/${id}`)

export const getMemorySettings = (api: ApiClient) => api.get<MemorySettings>('/memory/settings')

export const patchMemorySettings = (api: ApiClient, autoCapture: boolean) =>
  api.patch<MemorySettings>('/memory/settings', { auto_capture: autoCapture })
```

(If `ApiClient` is not exported from `../api/client`, check where `chat/chatApi.ts` imports it from and use that path.)

- [ ] **Step 4: Write the failing hook test** — create `frontend/src/memory/useFacts.test.tsx`:

```tsx
import { renderHook, waitFor, act } from '@testing-library/react'
import { server, http, HttpResponse } from '../test/msw'
import { AuthProvider } from '../auth/AuthContext'
import { useFacts } from './useFacts'

const wrapper = ({ children }: { children: React.ReactNode }) => <AuthProvider>{children}</AuthProvider>

beforeEach(() =>
  localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'r' })),
)

const fact = {
  id: '1',
  category: 'personal',
  content: 'Любит чай',
  source: 'manual',
  created_at: '2026-07-05T10:00:00Z',
  updated_at: '2026-07-05T10:00:00Z',
}

test('loads facts and settings on mount', async () => {
  server.use(
    http.get('/api/memory/facts', () => HttpResponse.json([fact])),
    http.get('/api/memory/settings', () => HttpResponse.json({ auto_capture: true })),
  )
  const { result } = renderHook(() => useFacts(), { wrapper })
  await waitFor(() => expect(result.current.loading).toBe(false))
  expect(result.current.facts[0].content).toBe('Любит чай')
  expect(result.current.autoCapture).toBe(true)
})

test('optimistically edits a fact and rolls back on failure', async () => {
  server.use(
    http.get('/api/memory/facts', () => HttpResponse.json([fact])),
    http.get('/api/memory/settings', () => HttpResponse.json({ auto_capture: true })),
    http.patch('/api/memory/facts/1', () => new HttpResponse(null, { status: 500 })),
  )
  const { result } = renderHook(() => useFacts(), { wrapper })
  await waitFor(() => expect(result.current.loading).toBe(false))

  await act(async () => {
    await result.current.editFact('1', { content: 'Обожает чай' })
  })
  // Reconciled back to the server's value after the failed PATCH.
  expect(result.current.facts[0].content).toBe('Любит чай')
})
```

- [ ] **Step 5: Run it, verify failure**

Run: `npm run test -- useFacts` (from `frontend/`)
Expected: FAIL (cannot resolve `./useFacts`).

- [ ] **Step 6: Implement the hook** — create `frontend/src/memory/useFacts.ts`:

```typescript
/** Facts + auto-capture state with optimistic mutations reconciled from the server on failure. */
import { useCallback, useEffect, useState } from 'react'
import { useApiClient } from '../auth/AuthContext'
import type { Category, FactOut, FactUpdate } from '../api/types'
import {
  createFact,
  deleteFact,
  getMemorySettings,
  listFacts,
  patchMemorySettings,
  updateFact,
} from './memoryApi'

/**
 * Load and mutate the current user's facts and the auto-capture toggle.
 *
 * Mutations update local state optimistically; on failure the list (or toggle) is
 * re-synced from the server via `reload`, so the UI never drifts from persisted state.
 */
export function useFacts() {
  const api = useApiClient()
  const [facts, setFacts] = useState<FactOut[]>([])
  const [autoCapture, setAutoCapture] = useState(true)
  const [loading, setLoading] = useState(true)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const [f, s] = await Promise.all([listFacts(api), getMemorySettings(api)])
      setFacts(f)
      setAutoCapture(s.auto_capture)
    } finally {
      setLoading(false)
    }
  }, [api])

  useEffect(() => {
    void reload()
  }, [reload])

  const addFact = useCallback(
    async (content: string, category: Category) => {
      const created = await createFact(api, content, category)
      setFacts((prev) => [created, ...prev])
      return created
    },
    [api],
  )

  const editFact = useCallback(
    async (id: string, patch: FactUpdate) => {
      setFacts((prev) => prev.map((f) => (f.id === id ? { ...f, ...patch } : f)))
      try {
        const updated = await updateFact(api, id, patch)
        setFacts((prev) => prev.map((f) => (f.id === id ? updated : f)))
      } catch {
        await reload()
      }
    },
    [api, reload],
  )

  const removeFact = useCallback(
    async (id: string) => {
      setFacts((prev) => prev.filter((f) => f.id !== id))
      try {
        await deleteFact(api, id)
      } catch {
        await reload()
      }
    },
    [api, reload],
  )

  const toggleAutoCapture = useCallback(
    async (value: boolean) => {
      setAutoCapture(value)
      try {
        const s = await patchMemorySettings(api, value)
        setAutoCapture(s.auto_capture)
      } catch {
        await reload()
      }
    },
    [api, reload],
  )

  return { facts, autoCapture, loading, reload, addFact, editFact, removeFact, toggleAutoCapture }
}
```

- [ ] **Step 7: Run tests + typecheck + lint**

Run: `npm run test -- useFacts && npm run typecheck && npm run lint`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/api/types.ts src/memory/categories.ts src/memory/memoryApi.ts src/memory/useFacts.ts src/memory/useFacts.test.tsx
git commit -m "feat(memory-ui): fact types, memoryApi, and useFacts hook"
```

---

## Task 2: `FactForm` and `FactCard` components

**Files:**
- Create: `frontend/src/components/FactForm.tsx` + `frontend/src/components/FactForm.module.css`
- Create: `frontend/src/components/FactCard.tsx` + `frontend/src/components/FactCard.module.css`
- Test: `frontend/src/components/FactForm.test.tsx`, `frontend/src/components/FactCard.test.tsx`

**Interfaces:**
- Consumes: `Category`, `FactOut` (types); `CATEGORIES`, `CATEGORY_BY_VALUE` (`../memory/categories`).
- Produces `FactForm` props: `{ initial?: { content: string; category: Category }; submitLabel?: string; onSubmit: (content: string, category: Category) => void; onCancel: () => void }`. Renders a content `<textarea>` (aria-label «Текст факта») + category `<select>` (aria-label «Категория») + save button (disabled when content is blank) + cancel button. Defaults: content `''`, category `'personal'`.
- Produces `FactCard` props: `{ fact: FactOut; onEdit: () => void; onDelete: () => void }`. Renders the coloured category tag, content, formatted RU date, and hover edit/delete buttons (aria-labels «Редактировать» / «Удалить»).

- [ ] **Step 1: Write the failing FactForm test** — create `frontend/src/components/FactForm.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FactForm } from './FactForm'

test('submits entered content and selected category', async () => {
  const onSubmit = vi.fn()
  render(<FactForm onSubmit={onSubmit} onCancel={() => {}} />)

  await userEvent.type(screen.getByLabelText('Текст факта'), 'Любит горы')
  await userEvent.selectOptions(screen.getByLabelText('Категория'), 'project')
  await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))

  expect(onSubmit).toHaveBeenCalledWith('Любит горы', 'project')
})

test('save is disabled until content is non-blank', async () => {
  render(<FactForm onSubmit={() => {}} onCancel={() => {}} />)
  expect(screen.getByRole('button', { name: 'Сохранить' })).toBeDisabled()
  await userEvent.type(screen.getByLabelText('Текст факта'), 'x')
  expect(screen.getByRole('button', { name: 'Сохранить' })).toBeEnabled()
})
```

- [ ] **Step 2: Run it, verify failure**

Run: `npm run test -- FactForm`
Expected: FAIL (cannot resolve `./FactForm`).

- [ ] **Step 3: Implement FactForm** — create `frontend/src/components/FactForm.tsx`:

```tsx
/** Inline form for creating or editing a fact: content textarea + category select. */
import { useState } from 'react'
import type { Category } from '../api/types'
import { CATEGORIES } from '../memory/categories'
import styles from './FactForm.module.css'

export function FactForm({
  initial,
  submitLabel = 'Сохранить',
  onSubmit,
  onCancel,
}: {
  initial?: { content: string; category: Category }
  submitLabel?: string
  onSubmit: (content: string, category: Category) => void
  onCancel: () => void
}) {
  const [content, setContent] = useState(initial?.content ?? '')
  const [category, setCategory] = useState<Category>(initial?.category ?? 'personal')

  const trimmed = content.trim()

  return (
    <div className={styles.form}>
      <textarea
        className={styles.textarea}
        aria-label="Текст факта"
        placeholder="Что запомнить?"
        value={content}
        onChange={(e) => setContent(e.target.value)}
        rows={3}
      />
      <div className={styles.row}>
        <select
          className={styles.select}
          aria-label="Категория"
          value={category}
          onChange={(e) => setCategory(e.target.value as Category)}
        >
          {CATEGORIES.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
        <div className={styles.actions}>
          <button type="button" className={styles.cancel} onClick={onCancel}>
            Отмена
          </button>
          <button
            type="button"
            className={styles.save}
            disabled={!trimmed}
            onClick={() => onSubmit(trimmed, category)}
          >
            {submitLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Add FactForm styles** — create `frontend/src/components/FactForm.module.css`:

```css
.form {
  display: flex;
  flex-direction: column;
  gap: 10px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.03);
  border-radius: 14px;
  padding: 14px 15px;
}
.textarea {
  width: 100%;
  resize: vertical;
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 9px;
  color: #e3dacf;
  font-family: inherit;
  font-size: 13.5px;
  line-height: 1.5;
  padding: 9px 10px;
}
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.select {
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  color: #d6cdc3;
  font-family: inherit;
  font-size: 13px;
  padding: 7px 9px;
}
.actions {
  display: flex;
  gap: 8px;
}
.cancel,
.save {
  border-radius: 8px;
  font-family: inherit;
  font-size: 13px;
  padding: 7px 14px;
  cursor: pointer;
  border: 1px solid transparent;
}
.cancel {
  background: transparent;
  border-color: rgba(255, 255, 255, 0.14);
  color: #c9c0b6;
}
.save {
  background: var(--accent, #d89b6c);
  color: #1a1712;
  font-weight: 600;
}
.save:disabled {
  opacity: 0.45;
  cursor: default;
}
```

- [ ] **Step 5: Run FactForm tests, verify pass**

Run: `npm run test -- FactForm`
Expected: PASS.

- [ ] **Step 6: Write the failing FactCard test** — create `frontend/src/components/FactCard.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FactCard } from './FactCard'
import type { FactOut } from '../api/types'

const fact: FactOut = {
  id: '1',
  category: 'project',
  content: 'Работает над CapybaraAgent',
  source: 'auto',
  created_at: '2026-07-05T10:00:00Z',
  updated_at: '2026-07-05T10:00:00Z',
}

test('renders the category label, content, and fires edit/delete', async () => {
  const onEdit = vi.fn()
  const onDelete = vi.fn()
  render(<FactCard fact={fact} onEdit={onEdit} onDelete={onDelete} />)

  expect(screen.getByText('Проект')).toBeInTheDocument()
  expect(screen.getByText('Работает над CapybaraAgent')).toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: 'Редактировать' }))
  expect(onEdit).toHaveBeenCalled()
  await userEvent.click(screen.getByRole('button', { name: 'Удалить' }))
  expect(onDelete).toHaveBeenCalled()
})
```

- [ ] **Step 7: Run it, verify failure**

Run: `npm run test -- FactCard`
Expected: FAIL (cannot resolve `./FactCard`).

- [ ] **Step 8: Implement FactCard** — create `frontend/src/components/FactCard.tsx`:

```tsx
/** A single fact: coloured category tag, content, date, and hover edit/delete actions. */
import { Pencil, Trash2 } from 'lucide-react'
import type { FactOut } from '../api/types'
import { CATEGORY_BY_VALUE } from '../memory/categories'
import styles from './FactCard.module.css'

/** Format an ISO timestamp as a RU long date, e.g. "5 июля 2026 г.". */
function formatDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })
}

export function FactCard({
  fact,
  onEdit,
  onDelete,
}: {
  fact: FactOut
  onEdit: () => void
  onDelete: () => void
}) {
  const meta = CATEGORY_BY_VALUE[fact.category]
  return (
    <div className={styles.card}>
      <div className={styles.head}>
        <span className={styles.tag} style={{ color: meta.color, background: meta.bg }}>
          {meta.label}
        </span>
        <div className={styles.actions}>
          <button type="button" className={styles.iconBtn} aria-label="Редактировать" onClick={onEdit}>
            <Pencil size={14} />
          </button>
          <button type="button" className={styles.iconBtn} aria-label="Удалить" onClick={onDelete}>
            <Trash2 size={14} />
          </button>
        </div>
      </div>
      <div className={styles.content}>{fact.content}</div>
      <div className={styles.date}>{formatDate(fact.created_at)}</div>
    </div>
  )
}
```

- [ ] **Step 9: Add FactCard styles** — create `frontend/src/components/FactCard.module.css`:

```css
.card {
  border: 1px solid rgba(255, 255, 255, 0.09);
  background: rgba(255, 255, 255, 0.03);
  border-radius: 14px;
  padding: 15px 16px;
  display: flex;
  flex-direction: column;
  gap: 9px;
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.tag {
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.3px;
  text-transform: uppercase;
  padding: 3px 8px;
  border-radius: 6px;
}
.actions {
  display: flex;
  gap: 4px;
  opacity: 0;
  transition: opacity 0.12s ease;
}
.card:hover .actions,
.card:focus-within .actions {
  opacity: 1;
}
.iconBtn {
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 7px;
  border: none;
  background: transparent;
  color: #8a8178;
  cursor: pointer;
}
.iconBtn:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #d6cdc3;
}
.content {
  font-size: 13.5px;
  line-height: 1.5;
  color: #e3dacf;
}
.date {
  font-size: 11px;
  color: #726a61;
  margin-top: auto;
}
```

- [ ] **Step 10: Run all Task-2 tests + typecheck + lint**

Run: `npm run test -- FactForm FactCard && npm run typecheck && npm run lint`
Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add src/components/FactForm.tsx src/components/FactForm.module.css src/components/FactForm.test.tsx src/components/FactCard.tsx src/components/FactCard.module.css src/components/FactCard.test.tsx
git commit -m "feat(memory-ui): FactForm and FactCard components"
```

---

## Task 3: `MemoryScreen`

**Files:**
- Create: `frontend/src/screens/MemoryScreen.tsx` + `frontend/src/screens/MemoryScreen.module.css`
- Test: `frontend/src/screens/MemoryScreen.test.tsx`

**Interfaces:**
- Consumes: `useFacts` (Task 1), `FactCard`, `FactForm` (Task 2).
- Produces: `MemoryScreen` (no props) — a header («Память» + fact-count subtitle + «Авто-запоминание» checkbox toggle), a 2-column fact-card grid where an editing card is replaced by an inline `FactForm`, and a dashed «Добавить факт вручную» button that reveals an inline `FactForm` for creation.

- [ ] **Step 1: Write the failing test** — create `frontend/src/screens/MemoryScreen.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, http, HttpResponse } from '../test/msw'
import { AuthProvider } from '../auth/AuthContext'
import { MemoryScreen } from './MemoryScreen'

beforeEach(() =>
  localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'r' })),
)

const fact = {
  id: '1',
  category: 'personal',
  content: 'Любит чай',
  source: 'manual',
  created_at: '2026-07-05T10:00:00Z',
  updated_at: '2026-07-05T10:00:00Z',
}

function renderScreen() {
  return render(
    <AuthProvider>
      <MemoryScreen />
    </AuthProvider>,
  )
}

test('renders facts and adds a new one', async () => {
  const created = { ...fact, id: '2', content: 'Пьёт кофе по утрам', category: 'preference' }
  server.use(
    http.get('/api/memory/facts', () => HttpResponse.json([fact])),
    http.get('/api/memory/settings', () => HttpResponse.json({ auto_capture: true })),
    http.post('/api/memory/facts', () => HttpResponse.json(created, { status: 201 })),
  )
  renderScreen()

  expect(await screen.findByText('Любит чай')).toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: /Добавить факт/ }))
  await userEvent.type(screen.getByLabelText('Текст факта'), 'Пьёт кофе по утрам')
  await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))

  expect(await screen.findByText('Пьёт кофе по утрам')).toBeInTheDocument()
})

test('deletes a fact', async () => {
  server.use(
    http.get('/api/memory/facts', () => HttpResponse.json([fact])),
    http.get('/api/memory/settings', () => HttpResponse.json({ auto_capture: true })),
    http.delete('/api/memory/facts/1', () => new HttpResponse(null, { status: 204 })),
  )
  renderScreen()
  expect(await screen.findByText('Любит чай')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Удалить' }))
  await waitFor(() => expect(screen.queryByText('Любит чай')).not.toBeInTheDocument())
})

test('toggles auto-capture', async () => {
  let patched: unknown = null
  server.use(
    http.get('/api/memory/facts', () => HttpResponse.json([])),
    http.get('/api/memory/settings', () => HttpResponse.json({ auto_capture: true })),
    http.patch('/api/memory/settings', async ({ request }) => {
      patched = await request.json()
      return HttpResponse.json({ auto_capture: false })
    }),
  )
  renderScreen()
  const toggle = await screen.findByLabelText('Авто-запоминание')
  await userEvent.click(toggle)
  await waitFor(() => expect(patched).toEqual({ auto_capture: false }))
})
```

- [ ] **Step 2: Run it, verify failure**

Run: `npm run test -- MemoryScreen`
Expected: FAIL (cannot resolve `./MemoryScreen`).

- [ ] **Step 3: Implement MemoryScreen** — create `frontend/src/screens/MemoryScreen.tsx`:

```tsx
/** Standalone «Память» screen: auto-capture toggle + fact-card grid with add/edit/delete. */
import { useState } from 'react'
import { Plus } from 'lucide-react'
import { FactCard } from '../components/FactCard'
import { FactForm } from '../components/FactForm'
import { useFacts } from '../memory/useFacts'
import type { Category } from '../api/types'
import styles from './MemoryScreen.module.css'

export function MemoryScreen() {
  const { facts, autoCapture, addFact, editFact, removeFact, toggleAutoCapture } = useFacts()
  const [editingId, setEditingId] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)

  async function handleAdd(content: string, category: Category) {
    await addFact(content, category)
    setAdding(false)
  }

  async function handleEdit(id: string, content: string, category: Category) {
    await editFact(id, { content, category })
    setEditingId(null)
  }

  return (
    <div className={styles.screen}>
      <div className={styles.inner}>
        <div className={styles.header}>
          <div>
            <h2 className={styles.title}>Память</h2>
            <p className={styles.subtitle}>
              Агент запомнил {facts.length} фактов о вас и вашей работе.
            </p>
          </div>
          <label className={styles.toggleLabel}>
            Авто-запоминание
            <input
              type="checkbox"
              className={styles.toggle}
              aria-label="Авто-запоминание"
              checked={autoCapture}
              onChange={(e) => void toggleAutoCapture(e.target.checked)}
            />
          </label>
        </div>

        <div className={styles.grid}>
          {facts.map((fact) =>
            editingId === fact.id ? (
              <FactForm
                key={fact.id}
                initial={{ content: fact.content, category: fact.category }}
                onSubmit={(content, category) => void handleEdit(fact.id, content, category)}
                onCancel={() => setEditingId(null)}
              />
            ) : (
              <FactCard
                key={fact.id}
                fact={fact}
                onEdit={() => setEditingId(fact.id)}
                onDelete={() => void removeFact(fact.id)}
              />
            ),
          )}
        </div>

        {adding ? (
          <div className={styles.addForm}>
            <FactForm
              submitLabel="Добавить"
              onSubmit={(content, category) => void handleAdd(content, category)}
              onCancel={() => setAdding(false)}
            />
          </div>
        ) : (
          <button type="button" className={styles.addBtn} onClick={() => setAdding(true)}>
            <Plus size={16} />
            Добавить факт вручную
          </button>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Add MemoryScreen styles** — create `frontend/src/screens/MemoryScreen.module.css`:

```css
.screen {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.inner {
  max-width: 760px;
  margin: 0 auto;
  padding: 40px 28px 60px;
}
.header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 22px;
}
.title {
  font-family: 'Space Grotesk', sans-serif;
  font-size: 24px;
  font-weight: 600;
  letter-spacing: -0.5px;
  margin: 0 0 6px;
  color: #f0e6db;
}
.subtitle {
  color: #a29a90;
  font-size: 14px;
  margin: 0;
}
.toggleLabel {
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 13px;
  color: #c9c0b6;
  flex-shrink: 0;
  cursor: pointer;
  padding-top: 4px;
}
.toggle {
  width: 18px;
  height: 18px;
  accent-color: var(--accent, #d89b6c);
  cursor: pointer;
}
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.addForm {
  margin-top: 14px;
}
.addBtn {
  width: 100%;
  margin-top: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 13px;
  border: 1.5px dashed rgba(255, 255, 255, 0.14);
  background: transparent;
  border-radius: 14px;
  color: #a29a90;
  font-size: 13.5px;
  font-weight: 500;
  cursor: pointer;
  font-family: inherit;
}
.addBtn:hover {
  background: rgba(255, 255, 255, 0.03);
}
```

- [ ] **Step 5: Run MemoryScreen tests + typecheck + lint**

Run: `npm run test -- MemoryScreen && npm run typecheck && npm run lint`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/screens/MemoryScreen.tsx src/screens/MemoryScreen.module.css src/screens/MemoryScreen.test.tsx
git commit -m "feat(memory-ui): MemoryScreen with grid, add/edit/delete, auto-capture toggle"
```

---

## Task 4: Sidebar «Память» nav + `ChatScreen` view switch

**Files:**
- Modify: `frontend/src/components/Sidebar.tsx` (props + bottom nav)
- Modify: `frontend/src/components/Sidebar.module.css` (nav button styles)
- Modify: `frontend/src/screens/ChatScreen.tsx` (`view` state + wiring)
- Test: `frontend/src/screens/MemoryNav.test.tsx`

**Interfaces:**
- Consumes: `MemoryScreen` (Task 3).
- Produces: `Sidebar` gains `onOpenMemory: () => void` and `memoryActive: boolean` props; the «Память» item is an enabled `<button>` (active class when `memoryActive`). `ChatScreen` gains `view: 'chat' | 'memory'`; selecting a chat / «Новый чат» sets `view='chat'`; «Память» sets `view='memory'`; `<main>` renders `MemoryScreen` when `view === 'memory'`.

- [ ] **Step 1: Write the failing navigation test** — create `frontend/src/screens/MemoryNav.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, http, HttpResponse } from '../test/msw'
import { AuthProvider } from '../auth/AuthContext'
import { ChatScreen } from './ChatScreen'

beforeEach(() =>
  localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'r' })),
)

test('clicking «Память» swaps main to the memory screen and back', async () => {
  server.use(
    http.get('/api/models', () => HttpResponse.json({ provider: 'ollama', models: ['llama3.1:8b'] })),
    http.get('/api/chats', () => HttpResponse.json([])),
    http.get('/api/memory/facts', () => HttpResponse.json([])),
    http.get('/api/memory/settings', () => HttpResponse.json({ auto_capture: true })),
  )
  render(
    <AuthProvider>
      <ChatScreen />
    </AuthProvider>,
  )

  // Starts on the chat welcome state.
  expect(await screen.findByText(/Чем помочь/)).toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: 'Память' }))
  // Memory screen header appears (heading role disambiguates from the nav button).
  expect(await screen.findByRole('heading', { name: 'Память' })).toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: 'Новый чат' }))
  expect(await screen.findByText(/Чем помочь/)).toBeInTheDocument()
})
```

- [ ] **Step 2: Run it, verify failure**

Run: `npm run test -- MemoryNav`
Expected: FAIL (no button named «Память» — it is a disabled `<div>`).

- [ ] **Step 3: Add the Sidebar props** — in `frontend/src/components/Sidebar.tsx`, add two props. Change the destructuring (currently ends `onDelete,`) and the type block:

In the destructuring list (after `onDelete,`) add:
```tsx
  onOpenMemory,
  memoryActive,
```

In the props type (after `onDelete: (id: string) => void`) add:
```tsx
  /** Open the standalone «Память» screen. */
  onOpenMemory: () => void
  /** True when the «Память» screen is the active view (highlights the nav item). */
  memoryActive: boolean
```

- [ ] **Step 4: Enable the «Память» nav item** — in `frontend/src/components/Sidebar.tsx`, replace the disabled «Память» `<div>` (the first child of `bottomBlock`):

```tsx
          <div aria-disabled="true" className={styles.navDisabled}>
            <Brain size={16} />
            Память
          </div>
```

with:

```tsx
          <button
            type="button"
            className={memoryActive ? `${styles.navButton} ${styles.navButtonActive}` : styles.navButton}
            onClick={onOpenMemory}
          >
            <Brain size={16} />
            Память
          </button>
```

(«Фоновые задачи» and «Настройки» stay as disabled `<div>` placeholders.)

- [ ] **Step 5: Add the nav-button styles** — append to `frontend/src/components/Sidebar.module.css`:

```css
.navButton {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 9px;
  border: 1px solid transparent;
  background: transparent;
  color: #c9c0b6;
  font-family: inherit;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.12s ease;
}
.navButton:hover {
  background: rgba(255, 255, 255, 0.06);
}
.navButtonActive,
.navButtonActive:hover {
  background: rgba(216, 155, 108, 0.13);
  border-color: rgba(216, 155, 108, 0.28);
  color: #f0e6db;
}
```

- [ ] **Step 6: Wire the view switch in ChatScreen** — in `frontend/src/screens/ChatScreen.tsx`:

Add the import (near the other screen/component imports):
```tsx
import { MemoryScreen } from './MemoryScreen'
```

Add the state (after the `sidebarCollapsed` state, ~line 45):
```tsx
  const [view, setView] = useState<'chat' | 'memory'>('chat')
```

Update the `Sidebar` element (lines 177–187) — change `onSelect`/`onNewChat` and add the two new props:
```tsx
        <Sidebar
          chats={chats}
          activeChatId={activeChatId}
          collapsed={sidebarCollapsed}
          onToggleCollapse={toggleSidebar}
          onSelect={(id) => {
            setActiveChatId(id)
            setView('chat')
          }}
          onNewChat={() => {
            setActiveChatId(null)
            setView('chat')
          }}
          onToggleFavorite={handleToggleFavorite}
          onRename={handleRename}
          onDelete={handleDelete}
          onOpenMemory={() => setView('memory')}
          memoryActive={view === 'memory'}
        />
```

Wrap the existing welcome/active conditional so memory takes precedence. Replace the block that currently reads `{activeChatId === null ? ( … welcome … ) : ( … active … )}` (lines 199–240) by wrapping it in an outer memory check — change the opening from:
```tsx
          {activeChatId === null ? (
```
to:
```tsx
          {view === 'memory' ? (
            <MemoryScreen />
          ) : activeChatId === null ? (
```
(The rest of the welcome and active branches, and the closing `)}`, stay unchanged — this adds one leading ternary arm. The `expandBtn` above it is untouched.)

- [ ] **Step 7: Run the nav test + the full frontend suite (regression)**

Run: `npm run test && npm run typecheck && npm run lint`
Expected: PASS — `MemoryNav` green and no regression in existing `ChatScreen`/`Sidebar` tests. (The existing `Sidebar` tests construct the component; if any instantiate `<Sidebar>` directly without the new required props, they will fail to typecheck — update those call sites to pass `onOpenMemory={() => {}} memoryActive={false}`. Search: `npm run test -- Sidebar` and check `grep -rn "<Sidebar" src`.)

- [ ] **Step 8: Commit**

```bash
git add src/components/Sidebar.tsx src/components/Sidebar.module.css src/screens/ChatScreen.tsx src/screens/MemoryNav.test.tsx
git commit -m "feat(memory-ui): sidebar «Память» nav and ChatScreen view switch"
```

---

## Task 5: Final verification

**Files:** none (verification only).

- [ ] **Step 1: Run every gate**

Run (from `frontend/`):
```bash
npm run lint && npm run typecheck && npx prettier --check . && npm run test && npm run build
```
Expected: all green. If `prettier --check` reports files, run `npm run format`, then re-run the gate and commit the formatting:
```bash
git add -p   # stage only the files you created/edited in this slice
git commit -m "style(memory-ui): prettier formatting"
```
(If `git add -p` is unavailable in the environment, `git add` each memory-slice file by explicit path — never `git add -A`.)

- [ ] **Step 2: Report** the final gate output (lint / typecheck / prettier / test counts / build) — this is the whole-slice verification.

---

## Self-Review

**1. Spec coverage (Frontend section):**

| Spec item | Task |
|---|---|
| `ChatScreen` gains `view: 'chat' \| 'memory'`; `<main>` renders MemoryScreen; selecting chat/new chat → `'chat'` | 4 |
| Sidebar «Память» enabled button (loses `aria-disabled`) + `onOpenMemory` + `memoryActive`; «Фоновые задачи»/«Настройки» stay disabled | 4 |
| Types `Category`, `FactOut`, `FactCreate`, `FactUpdate`, `MemorySettings` | 1 |
| `memory/memoryApi.ts`: `listFacts/createFact/updateFact/deleteFact/getMemorySettings/patchMemorySettings` | 1 |
| `useFacts`: list + create/update/delete + toggle, optimistic + reconcile-on-failure | 1 |
| `MemoryScreen`: header «Память» + «Авто-запоминание» toggle → `patchMemorySettings`; 2-col grid gap 12px; dashed «Добавить факт» → inline `FactForm` | 3 |
| `FactCard`: coloured category tag, content, date, hover edit/delete; edit → inline `FactForm` | 2, 3 |
| Colours/spacing/radii per design tokens | 2, 3 (Global Constraints) |
| Tests: MemoryScreen render+add/edit/delete+toggle; useFacts optimistic+rollback; sidebar nav swaps `<main>` + highlights | 1, 3, 4 |

**2. Placeholder scan:** none — every step ships concrete code/commands.

**3. Type consistency:** `FactOut`/`Category` fields (`content`, `category`, `source`, snake_case dates) are used identically across `types.ts`, `memoryApi.ts`, `useFacts.ts`, `FactCard`, `FactForm`, `MemoryScreen`; `useFacts` returns `{facts, autoCapture, loading, reload, addFact, editFact, removeFact, toggleAutoCapture}` consumed exactly by `MemoryScreen`; `FactForm.onSubmit(content, category)` and `FactCard.onEdit/onDelete` signatures match their call sites; `Sidebar` new props (`onOpenMemory`, `memoryActive`) match the `ChatScreen` wiring.

**Known integration note for the implementer:** enabling the two new **required** `Sidebar` props means any existing test or code that renders `<Sidebar>` directly must pass them — Task 4 Step 7 calls this out and tells you how to find the call sites (`grep -rn "<Sidebar" src`).
