# Frontend Chat + Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a React web SPA (`frontend/`) that lets a user register/log in and hold a streaming chat with the agent, wired to the existing FastAPI chat-core backend over HTTP/SSE.

**Architecture:** Layered frontend mirroring the backend's discipline — `api/` (HTTP + SSE, framework-agnostic) → `auth/` and `chat/` (React Context + hooks own data/effects) → `components/` (presentational) → `screens/` composed by `App.tsx` (view = `'auth' | 'chat'`). The browser always talks to the same origin under `/api`, proxied to FastAPI (Vite proxy in dev, nginx in Docker) so no CORS work is needed. Streaming uses `fetch` + manual SSE parsing (not `EventSource`, which cannot POST or send a Bearer header).

**Tech Stack:** React 18, TypeScript (strict), Vite, CSS Modules + design-token CSS variables, lucide-react, Vitest + React Testing Library + MSW. Node 20 LTS.

## Global Constraints

- **Node:** 20 LTS. **React:** 18.x. **TypeScript:** strict mode on.
- **No backend change this slice.** No CORS added; the frontend calls the same origin under base path **`/api`**.
- **Auth is stateless JWT.** Send `Authorization: Bearer <token>`; logout = discard token client-side. There is **no** `GET /users/me`.
- **SSE via `fetch` + `ReadableStream`** parsing. Do **not** use `EventSource`.
- **Design source of truth:** `design_handoff_capybaraagent/README.md` tokens + `CapybaraAgent.dc.html`. On any conflict, the README tokens win. Recreate colors, glass, typography, radii, spacing faithfully.
- **Tests never contact a real backend or LLM** — MSW mocks HTTP and the SSE byte stream.
- **Fonts:** Space Grotesk (display), Hanken Grotesk (body, base 14px), JetBrains Mono (mono). **Accent** default `#D89B6C` via CSS var `--accent`.
- All commands below run from `frontend/` unless stated otherwise.

## File Structure

```
frontend/
  package.json, tsconfig.json, vite.config.ts, .eslintrc.cjs, .prettierrc, index.html
  Dockerfile, nginx.conf
  src/
    main.tsx, App.tsx, App.module.css
    vite-env.d.ts
    test/setup.ts, test/msw.ts
    theme/tokens.css, theme/global.css
    api/types.ts, api/client.ts, api/sse.ts
    auth/storage.ts, auth/AuthContext.tsx
    chat/chatApi.ts, chat/useChats.ts, chat/useChatStream.ts
    components/CapyLogo.tsx, components/BackgroundGlow.tsx (+ .module.css)
    components/Sidebar.tsx, components/ChatListItem.tsx, components/UserCard.tsx (+ .module.css)
    components/Composer.tsx, components/Message.tsx (+ .module.css)
    screens/AuthScreen.tsx (+ .module.css)
    screens/ChatScreen.tsx (+ .module.css)
  README.md
docker-compose.yml            # MODIFY at repo root: add `frontend` service
```

---

### Task 1: Scaffold the frontend project + tooling

**Files:**
- Create: `frontend/package.json`, `frontend/tsconfig.json`, `frontend/tsconfig.node.json`, `frontend/vite.config.ts`, `frontend/index.html`, `frontend/.eslintrc.cjs`, `frontend/.prettierrc`, `frontend/.gitignore`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/vite-env.d.ts`, `frontend/src/test/setup.ts`
- Test: `frontend/src/App.test.tsx`

**Interfaces:**
- Produces: a runnable Vite React+TS app; `npm run dev|build|test|lint`; Vitest configured with jsdom + RTL matchers; `App` default export rendering a placeholder.

- [ ] **Step 1: Ensure Node 20 is active**

Run (from repo root): `node --version`
If it prints < v20, run `nvm install 20 && nvm use 20` (install nvm first if missing). Expected: `v20.x`.

- [ ] **Step 2: Create `frontend/package.json`**

```json
{
  "name": "capybara-frontend",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "lint": "eslint . --max-warnings 0",
    "format": "prettier --write .",
    "test": "vitest run",
    "test:watch": "vitest",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "lucide-react": "^0.400.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.4.0",
    "@testing-library/react": "^16.0.0",
    "@testing-library/user-event": "^14.5.0",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@typescript-eslint/eslint-plugin": "^7.13.0",
    "@typescript-eslint/parser": "^7.13.0",
    "@vitejs/plugin-react": "^4.3.0",
    "eslint": "^8.57.0",
    "eslint-plugin-react-hooks": "^4.6.0",
    "eslint-plugin-react-refresh": "^0.4.7",
    "jsdom": "^24.1.0",
    "msw": "^2.3.0",
    "prettier": "^3.3.0",
    "typescript": "~5.4.5",
    "vite": "^5.3.0",
    "vitest": "^2.0.0"
  }
}
```

- [ ] **Step 3: Create config files**

`frontend/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

`frontend/tsconfig.node.json`:
```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts"]
}
```

`frontend/vite.config.ts` (dev proxy + Vitest config together):
```ts
/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: true,
  },
})
```

`frontend/.eslintrc.cjs`:
```cjs
module.exports = {
  root: true,
  env: { browser: true, es2022: true },
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
  ],
  parser: '@typescript-eslint/parser',
  plugins: ['react-refresh'],
  ignorePatterns: ['dist', '.eslintrc.cjs'],
  rules: {
    'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
  },
}
```

`frontend/.prettierrc`:
```json
{ "semi": false, "singleQuote": true, "trailingComma": "all", "printWidth": 100 }
```

`frontend/.gitignore`:
```
node_modules
dist
*.local
```

- [ ] **Step 4: Create app entry + placeholder**

`frontend/index.html`:
```html
<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>CapybaraAgent</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`frontend/src/vite-env.d.ts`:
```ts
/// <reference types="vite/client" />
```

`frontend/src/main.tsx`:
```tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
```

`frontend/src/App.tsx`:
```tsx
/** Root component; view routing arrives in Task 7. */
export default function App() {
  return <div>CapybaraAgent</div>
}
```

`frontend/src/test/setup.ts`:
```ts
import '@testing-library/jest-dom/vitest'
```

- [ ] **Step 5: Write the smoke test**

`frontend/src/App.test.tsx`:
```tsx
import { render, screen } from '@testing-library/react'
import App from './App'

test('renders app name', () => {
  render(<App />)
  expect(screen.getByText('CapybaraAgent')).toBeInTheDocument()
})
```

- [ ] **Step 6: Install and verify the toolchain**

Run: `cd frontend && npm install && npm run test && npm run lint && npm run build`
Expected: install succeeds; test PASSES; lint clean; build emits `dist/`.

- [ ] **Step 7: Commit**

```bash
git add frontend
git commit -m "chore(frontend): scaffold Vite + React + TS with Vitest and tooling"
```

---

### Task 2: Theme layer — tokens, background, CapyLogo

**Files:**
- Create: `frontend/src/theme/tokens.css`, `frontend/src/theme/global.css`, `frontend/src/components/CapyLogo.tsx`, `frontend/src/components/BackgroundGlow.tsx`, `frontend/src/components/BackgroundGlow.module.css`
- Test: `frontend/src/components/CapyLogo.test.tsx`
- Modify: `frontend/src/main.tsx` (import global styles)

**Interfaces:**
- Produces:
  - CSS variables in `:root` (from README §"Design Tokens"): `--accent: #D89B6C`, `--bg:#0d0c0b`, `--glow-a`, `--glow-b`, text colors (`--text-primary:#F2ECE4`, `--text-secondary:#e8dfd5`, `--text-muted:#a29a90`, `--text-faint:#8a8178`), status colors (`--success:#6FBF8E`, `--error:#E08A7A`, `--warn:#E0B15A`), plus keyframes `drift`, `drift2`, `blink`, `spin`, `pulse`.
  - `CapyLogo({ size }: { size: number }): JSX.Element` — inline SVG, `viewBox="0 0 32 32"`, fill `var(--accent)`.
  - `BackgroundGlow(): JSX.Element` — the two drifting radial glows + base background.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/CapyLogo.test.tsx`:
```tsx
import { render } from '@testing-library/react'
import { CapyLogo } from './CapyLogo'

test('renders an svg at the requested size', () => {
  const { container } = render(<CapyLogo size={40} />)
  const svg = container.querySelector('svg')
  expect(svg).toBeInTheDocument()
  expect(svg).toHaveAttribute('width', '40')
  expect(svg).toHaveAttribute('viewBox', '0 0 32 32')
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- CapyLogo`
Expected: FAIL — cannot find module `./CapyLogo`.

- [ ] **Step 3: Implement CapyLogo** (SVG paths copied verbatim from `CapybaraAgent.dc.html:42`)

`frontend/src/components/CapyLogo.tsx`:
```tsx
/** Capybara glyph. Fill inherits from --accent; eye is dark. */
export function CapyLogo({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <circle cx="12" cy="9.2" r="2.7" fill="var(--accent,#D89B6C)" />
      <rect x="6.5" y="10.5" width="22" height="12" rx="6" fill="var(--accent,#D89B6C)" />
      <rect x="2.2" y="13.8" width="10.5" height="8" rx="4" fill="var(--accent,#D89B6C)" />
      <rect x="10.8" y="20.5" width="3.8" height="5.4" rx="1.6" fill="var(--accent,#D89B6C)" />
      <rect x="21.4" y="20.5" width="3.8" height="5.4" rx="1.6" fill="var(--accent,#D89B6C)" />
      <circle cx="7.3" cy="15.4" r="1.15" fill="#1c140d" />
    </svg>
  )
}
```

- [ ] **Step 4: Create `tokens.css` and `global.css`**

`frontend/src/theme/tokens.css` — declare every variable named in the Interfaces block above under `:root`, using the exact hex/rgba values from README §"Design Tokens", and the five `@keyframes` copied verbatim from `CapybaraAgent.dc.html:22-26` (`drift`, `drift2`, `blink`, `spin`, `pulse`).

`frontend/src/theme/global.css` — `@import` the three Google Fonts (Space Grotesk, Hanken Grotesk, JetBrains Mono); `html,body{margin:0;padding:0;height:100%;background:var(--bg);}`; set body font to Hanken Grotesk 14px, color `var(--text-primary)`, `-webkit-font-smoothing:antialiased`; add `@media (prefers-reduced-motion: reduce){ [data-anim]{animation:none !important;} }`.

- [ ] **Step 5: Implement BackgroundGlow** (values from `CapybaraAgent.dc.html:33-34`)

`frontend/src/components/BackgroundGlow.module.css` — `.root` = `position:fixed;inset:0;overflow:hidden;pointer-events:none;background:var(--bg)`; `.glowA` and `.glowB` reproduce the two radial-gradient circles (top-left warm w/ `animation:drift 24s`, bottom-right cool w/ `animation:drift2 28s`), each `filter:blur(30px)`, with `data-anim` on the elements.

`frontend/src/components/BackgroundGlow.tsx`:
```tsx
import styles from './BackgroundGlow.module.css'

/** Fixed wallpaper: base color + two slowly drifting radial glows. */
export function BackgroundGlow() {
  return (
    <div className={styles.root} aria-hidden="true">
      <div className={styles.glowA} data-anim />
      <div className={styles.glowB} data-anim />
    </div>
  )
}
```

- [ ] **Step 6: Wire global styles**

In `frontend/src/main.tsx`, add at the top: `import './theme/tokens.css'` and `import './theme/global.css'`.

- [ ] **Step 7: Run tests + typecheck**

Run: `npm run test -- CapyLogo && npm run typecheck`
Expected: PASS; no type errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/theme frontend/src/components/CapyLogo.tsx frontend/src/components/BackgroundGlow.tsx frontend/src/components/BackgroundGlow.module.css frontend/src/components/CapyLogo.test.tsx frontend/src/main.tsx
git commit -m "feat(frontend): design tokens, background wallpaper, capybara glyph"
```

---

### Task 3: API types + HTTP client

**Files:**
- Create: `frontend/src/api/types.ts`, `frontend/src/api/client.ts`
- Test: `frontend/src/api/client.test.ts`, `frontend/src/test/msw.ts`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `types.ts`: `UserOut { id: string; username: string; display_name: string; created_at: string }`; `TokenResponse { access_token: string; token_type: string }`; `ChatOut { id: string; title: string; created_at: string; updated_at: string }`; `MessageOut { id: string; role: string; content: string; model: string | null; incomplete: boolean; created_at: string }`; `ChatDetailOut = ChatOut & { messages: MessageOut[] }`.
  - `client.ts`: `class ApiError extends Error { status: number }`; `createApiClient(opts: { getToken: () => string | null; onUnauthorized: () => void }): ApiClient` where `ApiClient` has `get<T>(path): Promise<T>`, `post<T>(path, body?): Promise<T>`, and `stream(path, body): Promise<Response>` (returns the raw streaming Response for SSE). All prefix `/api`, attach `Authorization: Bearer <token>` when present, `Content-Type: application/json` for bodies, throw `ApiError` on non-2xx, and call `onUnauthorized()` on 401.

- [ ] **Step 1: Create the MSW test harness**

`frontend/src/test/msw.ts`:
```ts
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'

export const server = setupServer()
export { http, HttpResponse }
```

Append to `frontend/src/test/setup.ts`:
```ts
import { server } from './msw'
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())
```

- [ ] **Step 2: Write the failing test**

`frontend/src/api/client.test.ts`:
```ts
import { server, http, HttpResponse } from '../test/msw'
import { createApiClient, ApiError } from './client'

test('get attaches bearer token and parses json', async () => {
  server.use(
    http.get('/api/chats', ({ request }) => {
      expect(request.headers.get('Authorization')).toBe('Bearer t0ken')
      return HttpResponse.json([{ id: '1', title: 'Hi' }])
    }),
  )
  const client = createApiClient({ getToken: () => 't0ken', onUnauthorized: () => {} })
  const chats = await client.get<{ id: string }[]>('/chats')
  expect(chats[0].id).toBe('1')
})

test('401 throws ApiError and calls onUnauthorized', async () => {
  server.use(http.get('/api/chats', () => new HttpResponse(null, { status: 401 })))
  const onUnauthorized = vi.fn()
  const client = createApiClient({ getToken: () => null, onUnauthorized })
  await expect(client.get('/chats')).rejects.toBeInstanceOf(ApiError)
  expect(onUnauthorized).toHaveBeenCalledOnce()
})
```

- [ ] **Step 3: Run test to verify it fails**

Run: `npm run test -- client`
Expected: FAIL — cannot find `./client`.

- [ ] **Step 4: Implement types + client**

`frontend/src/api/types.ts` — the interfaces exactly as in the Interfaces block.

`frontend/src/api/client.ts`:
```ts
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export interface ApiClient {
  get<T>(path: string): Promise<T>
  post<T>(path: string, body?: unknown): Promise<T>
  stream(path: string, body: unknown): Promise<Response>
}

export function createApiClient(opts: {
  getToken: () => string | null
  onUnauthorized: () => void
}): ApiClient {
  async function request(path: string, init: RequestInit): Promise<Response> {
    const token = opts.getToken()
    const headers = new Headers(init.headers)
    if (token) headers.set('Authorization', `Bearer ${token}`)
    const res = await fetch(`/api${path}`, { ...init, headers })
    if (res.status === 401) {
      opts.onUnauthorized()
      throw new ApiError(401, 'Unauthorized')
    }
    return res
  }
  async function json<T>(path: string, init: RequestInit): Promise<T> {
    const res = await request(path, init)
    if (!res.ok) throw new ApiError(res.status, await res.text())
    return (await res.json()) as T
  }
  return {
    get: (path) => json(path, { method: 'GET' }),
    post: (path, body) =>
      json(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      }),
    stream: (path, body) =>
      request(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
  }
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npm run test -- client`
Expected: PASS (both tests).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/api/client.test.ts frontend/src/test
git commit -m "feat(frontend): typed API client with bearer auth and 401 handling"
```

---

### Task 4: SSE stream parser

**Files:**
- Create: `frontend/src/api/sse.ts`
- Test: `frontend/src/api/sse.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `type SseEvent = { event: string; data: string }`; `async function* parseSse(stream: ReadableStream<Uint8Array>): AsyncGenerator<SseEvent>` — decodes bytes, splits on blank lines, yields `{ event, data }` per SSE block (default event `'message'` if no `event:` line). Handles chunk boundaries mid-event.

- [ ] **Step 1: Write the failing test**

`frontend/src/api/sse.test.ts`:
```ts
import { parseSse, type SseEvent } from './sse'

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c))
      controller.close()
    },
  })
}

test('parses events split across chunk boundaries', async () => {
  const stream = streamOf([
    'event: delta\ndata: {"text":"Hel',
    'lo"}\n\nevent: done\ndata: {"message_id":"m1"}\n\n',
  ])
  const events: SseEvent[] = []
  for await (const e of parseSse(stream)) events.push(e)
  expect(events).toEqual([
    { event: 'delta', data: '{"text":"Hello"}' },
    { event: 'done', data: '{"message_id":"m1"}' },
  ])
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- sse`
Expected: FAIL — cannot find `./sse`.

- [ ] **Step 3: Implement the parser**

`frontend/src/api/sse.ts`:
```ts
export type SseEvent = { event: string; data: string }

/** Parse a fetch ReadableStream of SSE bytes into typed events. */
export async function* parseSse(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<SseEvent> {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let sep: number
      while ((sep = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, sep)
        buffer = buffer.slice(sep + 2)
        yield parseBlock(block)
      }
    }
  } finally {
    reader.releaseLock()
  }
}

function parseBlock(block: string): SseEvent {
  let event = 'message'
  const data: string[] = []
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data.push(line.slice(5).trim())
  }
  return { event, data: data.join('\n') }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- sse`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/sse.ts frontend/src/api/sse.test.ts
git commit -m "feat(frontend): SSE stream parser tolerant of chunk boundaries"
```

---

### Task 5: Auth storage + AuthContext

**Files:**
- Create: `frontend/src/auth/storage.ts`, `frontend/src/auth/AuthContext.tsx`
- Test: `frontend/src/auth/AuthContext.test.tsx`

**Interfaces:**
- Consumes: `createApiClient`, `ApiError`, `types.ts` (Task 3).
- Produces:
  - `storage.ts`: `loadSession(): { token: string; username: string } | null`; `saveSession(s): void`; `clearSession(): void` — backed by `localStorage` key `capybara.session`.
  - `AuthContext.tsx`: `AuthProvider` component; `useAuth(): { user: { username: string; displayName: string } | null; token: string | null; login(username, password): Promise<void>; register(displayName, username, password): Promise<void>; logout(): void }`. `login` POSTs `/auth/login`, stores token+username; `register` POSTs `/users`, then logs in; `logout` clears storage + state. A shared `apiClient` is created here with `onUnauthorized` wired to `logout`, and exposed via `useApiClient()`.

- [ ] **Step 1: Write the failing test**

`frontend/src/auth/AuthContext.test.tsx`:
```tsx
import { act, renderHook, waitFor } from '@testing-library/react'
import { server, http, HttpResponse } from '../test/msw'
import { AuthProvider, useAuth } from './AuthContext'

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <AuthProvider>{children}</AuthProvider>
)

beforeEach(() => localStorage.clear())

test('login stores token and username', async () => {
  server.use(
    http.post('/api/auth/login', () =>
      HttpResponse.json({ access_token: 'jwt123', token_type: 'bearer' }),
    ),
  )
  const { result } = renderHook(() => useAuth(), { wrapper })
  await act(() => result.current.login('roman', 'password1'))
  await waitFor(() => expect(result.current.token).toBe('jwt123'))
  expect(result.current.user?.username).toBe('roman')
  expect(JSON.parse(localStorage.getItem('capybara.session')!).token).toBe('jwt123')
})

test('logout clears session', async () => {
  localStorage.setItem(
    'capybara.session',
    JSON.stringify({ token: 'x', username: 'roman' }),
  )
  const { result } = renderHook(() => useAuth(), { wrapper })
  expect(result.current.token).toBe('x')
  act(() => result.current.logout())
  expect(result.current.token).toBeNull()
  expect(localStorage.getItem('capybara.session')).toBeNull()
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- AuthContext`
Expected: FAIL — cannot find `./AuthContext`.

- [ ] **Step 3: Implement storage**

`frontend/src/auth/storage.ts`:
```ts
const KEY = 'capybara.session'
export type Session = { token: string; username: string }

export function loadSession(): Session | null {
  const raw = localStorage.getItem(KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as Session
  } catch {
    return null
  }
}
export function saveSession(s: Session): void {
  localStorage.setItem(KEY, JSON.stringify(s))
}
export function clearSession(): void {
  localStorage.removeItem(KEY)
}
```

- [ ] **Step 4: Implement AuthContext**

`frontend/src/auth/AuthContext.tsx`:
```tsx
import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'
import { createApiClient, type ApiClient } from '../api/client'
import type { TokenResponse, UserOut } from '../api/types'
import { clearSession, loadSession, saveSession } from './storage'

type User = { username: string; displayName: string }
type AuthValue = {
  user: User | null
  token: string | null
  login: (username: string, password: string) => Promise<void>
  register: (displayName: string, username: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthValue | null>(null)
const ApiContext = createContext<ApiClient | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const initial = loadSession()
  const [token, setToken] = useState<string | null>(initial?.token ?? null)
  const [user, setUser] = useState<User | null>(
    initial ? { username: initial.username, displayName: initial.username } : null,
  )
  const tokenRef = useRef<string | null>(token)
  tokenRef.current = token

  const logout = useCallback(() => {
    clearSession()
    setToken(null)
    setUser(null)
  }, [])

  const api = useMemo(
    () => createApiClient({ getToken: () => tokenRef.current, onUnauthorized: logout }),
    [logout],
  )

  const login = useCallback(
    async (username: string, password: string) => {
      const res = await api.post<TokenResponse>('/auth/login', { username, password })
      saveSession({ token: res.access_token, username })
      setToken(res.access_token)
      setUser({ username, displayName: username })
    },
    [api],
  )

  const register = useCallback(
    async (displayName: string, username: string, password: string) => {
      await api.post<UserOut>('/users', {
        display_name: displayName,
        username,
        password,
      })
      await login(username, password)
    },
    [api, login],
  )

  const value = useMemo<AuthValue>(
    () => ({ user, token, login, register, logout }),
    [user, token, login, register, logout],
  )
  return (
    <ApiContext.Provider value={api}>
      <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
    </ApiContext.Provider>
  )
}

export function useAuth(): AuthValue {
  const v = useContext(AuthContext)
  if (!v) throw new Error('useAuth must be used within AuthProvider')
  return v
}
export function useApiClient(): ApiClient {
  const v = useContext(ApiContext)
  if (!v) throw new Error('useApiClient must be used within AuthProvider')
  return v
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npm run test -- AuthContext`
Expected: PASS (both tests).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/auth
git commit -m "feat(frontend): AuthContext with persisted JWT session and shared API client"
```

---

### Task 6: AuthScreen (login / register)

**Files:**
- Create: `frontend/src/screens/AuthScreen.tsx`, `frontend/src/screens/AuthScreen.module.css`
- Test: `frontend/src/screens/AuthScreen.test.tsx`

**Interfaces:**
- Consumes: `useAuth` (Task 5), `CapyLogo` (Task 2), `ApiError` (Task 3).
- Produces: `AuthScreen(): JSX.Element` — glass card centered (`max-width:396px`); `mode: 'login' | 'register'` local state; login fields Логин/Пароль, register fields Имя/Логин/Пароль; submit calls `useAuth().login`/`register`; on `ApiError` shows an inline message (401 → «Неверный логин или пароль», 409 → «Логин уже занят»); link toggles mode. Styling from README §"0. Auth".

- [ ] **Step 1: Write the failing test**

`frontend/src/screens/AuthScreen.test.tsx`:
```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, http, HttpResponse } from '../test/msw'
import { AuthProvider } from '../auth/AuthContext'
import { AuthScreen } from './AuthScreen'

const renderScreen = () =>
  render(
    <AuthProvider>
      <AuthScreen />
    </AuthProvider>,
  )

beforeEach(() => localStorage.clear())

test('shows inline error on invalid login', async () => {
  server.use(http.post('/api/auth/login', () => new HttpResponse(null, { status: 401 })))
  renderScreen()
  await userEvent.type(screen.getByLabelText('Логин'), 'roman')
  await userEvent.type(screen.getByLabelText('Пароль'), 'wrongpass')
  await userEvent.click(screen.getByRole('button', { name: 'Войти' }))
  expect(await screen.findByText('Неверный логин или пароль')).toBeInTheDocument()
})

test('can switch to register mode', async () => {
  renderScreen()
  await userEvent.click(screen.getByText('Создать пользователя'))
  expect(screen.getByRole('button', { name: 'Создать аккаунт' })).toBeInTheDocument()
  expect(screen.getByLabelText('Имя')).toBeInTheDocument()
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- AuthScreen`
Expected: FAIL — cannot find `./AuthScreen`.

- [ ] **Step 3: Implement AuthScreen**

Implement `AuthScreen.tsx` with the structure below; put all visual values in `AuthScreen.module.css` ported from README §"0. Auth" (glass card `rgba(28,24,20,.6)` blur(34px), inputs `padding:11×14 radius:11px`, primary accent button, footer lock line). Logic (copy verbatim):
```tsx
import { useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { CapyLogo } from '../components/CapyLogo'
import styles from './AuthScreen.module.css'

/** Full-screen login/register card shown while logged out. */
export function AuthScreen() {
  const { login, register } = useAuth()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [displayName, setDisplayName] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      if (mode === 'login') await login(username, password)
      else await register(displayName, username, password)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401)
        setError('Неверный логин или пароль')
      else if (err instanceof ApiError && err.status === 409)
        setError('Логин уже занят')
      else setError('Что-то пошло не так. Попробуйте ещё раз.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={styles.screen}>
      <div className={styles.header}>
        <CapyLogo size={60} />
        <div className={styles.wordmark}>CapybaraAgent</div>
        <div className={styles.tagline}>Локальный AI-агент</div>
      </div>
      <form className={styles.card} onSubmit={onSubmit}>
        <h1 className={styles.title}>
          {mode === 'login' ? 'С возвращением' : 'Создать пользователя'}
        </h1>
        {mode === 'register' && (
          <label className={styles.field}>
            <span>Имя</span>
            <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          </label>
        )}
        <label className={styles.field}>
          <span>Логин</span>
          <input value={username} onChange={(e) => setUsername(e.target.value)} />
        </label>
        <label className={styles.field}>
          <span>Пароль</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && <div className={styles.error}>{error}</div>}
        <button className={styles.primary} type="submit" disabled={busy}>
          {mode === 'login' ? 'Войти' : 'Создать аккаунт'}
        </button>
        <div className={styles.switch}>
          {mode === 'login' ? (
            <button type="button" onClick={() => setMode('register')}>
              Нет профиля? Создать пользователя
            </button>
          ) : (
            <button type="button" onClick={() => setMode('login')}>
              Уже есть профиль? Войти
            </button>
          )}
        </div>
      </form>
      <div className={styles.footer}>Всё хранится локально на вашем устройстве</div>
    </div>
  )
}
```
Note: the `<span>` inside each `<label>` provides the accessible name so `getByLabelText` works.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- AuthScreen`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/screens/AuthScreen.tsx frontend/src/screens/AuthScreen.module.css frontend/src/screens/AuthScreen.test.tsx
git commit -m "feat(frontend): auth screen with login/register modes and inline errors"
```

---

### Task 7: App shell — view routing by auth state

**Files:**
- Modify: `frontend/src/App.tsx`, `frontend/src/App.test.tsx`
- Create: `frontend/src/App.module.css`

**Interfaces:**
- Consumes: `AuthProvider`, `useAuth` (Task 5), `AuthScreen` (Task 6), `BackgroundGlow` (Task 2). `ChatScreen` is imported once Task 11 lands — until then render a placeholder `<div>chat</div>` behind the auth check.
- Produces: `App` renders `BackgroundGlow` + (`useAuth().token` ? chat view : `AuthScreen`), wrapped in `AuthProvider`.

- [ ] **Step 1: Replace the smoke test**

`frontend/src/App.test.tsx`:
```tsx
import { render, screen } from '@testing-library/react'
import App from './App'

beforeEach(() => localStorage.clear())

test('shows auth screen when logged out', () => {
  render(<App />)
  expect(screen.getByRole('button', { name: 'Войти' })).toBeInTheDocument()
})

test('shows chat view when a session exists', () => {
  localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'roman' }))
  render(<App />)
  expect(screen.queryByRole('button', { name: 'Войти' })).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- App`
Expected: FAIL — no «Войти» button (App still renders placeholder).

- [ ] **Step 3: Implement the shell**

`frontend/src/App.tsx`:
```tsx
import { AuthProvider, useAuth } from './auth/AuthContext'
import { AuthScreen } from './screens/AuthScreen'
import { BackgroundGlow } from './components/BackgroundGlow'
import styles from './App.module.css'

function Router() {
  const { token } = useAuth()
  return (
    <div className={styles.app}>
      <BackgroundGlow />
      {token ? <div>chat</div> : <AuthScreen />}
    </div>
  )
}

/** App root: wallpaper + auth-gated view. */
export default function App() {
  return (
    <AuthProvider>
      <Router />
    </AuthProvider>
  )
}
```

`frontend/src/App.module.css`: `.app{position:fixed;inset:0;display:flex;overflow:hidden;}`.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- App`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.module.css frontend/src/App.test.tsx
git commit -m "feat(frontend): auth-gated app shell over wallpaper"
```

---

### Task 8: Chat API + useChats hook

**Files:**
- Create: `frontend/src/chat/chatApi.ts`, `frontend/src/chat/useChats.ts`
- Test: `frontend/src/chat/useChats.test.tsx`

**Interfaces:**
- Consumes: `useApiClient` (Task 5), `ApiClient`, `ChatOut`, `ChatDetailOut` (Task 3).
- Produces:
  - `chatApi.ts`: `listChats(api): Promise<ChatOut[]>` → `GET /chats`; `createChat(api, title?): Promise<ChatOut>` → `POST /chats`; `getChat(api, id): Promise<ChatDetailOut>` → `GET /chats/{id}`.
  - `useChats.ts`: `useChats(): { chats: ChatOut[]; loading: boolean; reload(): Promise<void>; newChat(): Promise<ChatOut> }`. Loads on mount; `newChat` creates and prepends.

- [ ] **Step 1: Write the failing test**

`frontend/src/chat/useChats.test.tsx`:
```tsx
import { renderHook, waitFor, act } from '@testing-library/react'
import { server, http, HttpResponse } from '../test/msw'
import { AuthProvider } from '../auth/AuthContext'
import { useChats } from './useChats'

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <AuthProvider>{children}</AuthProvider>
)
beforeEach(() =>
  localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'r' })),
)

test('loads chats on mount and creates a new one', async () => {
  const chat = { id: '1', title: 'Новый чат', created_at: '', updated_at: '' }
  server.use(
    http.get('/api/chats', () => HttpResponse.json([])),
    http.post('/api/chats', () => HttpResponse.json(chat, { status: 201 })),
  )
  const { result } = renderHook(() => useChats(), { wrapper })
  await waitFor(() => expect(result.current.loading).toBe(false))
  expect(result.current.chats).toEqual([])
  await act(async () => {
    await result.current.newChat()
  })
  expect(result.current.chats[0].id).toBe('1')
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- useChats`
Expected: FAIL — cannot find `./useChats`.

- [ ] **Step 3: Implement chatApi + useChats**

`frontend/src/chat/chatApi.ts`:
```ts
import type { ApiClient } from '../api/client'
import type { ChatDetailOut, ChatOut } from '../api/types'

export const listChats = (api: ApiClient) => api.get<ChatOut[]>('/chats')
export const createChat = (api: ApiClient, title?: string) =>
  api.post<ChatOut>('/chats', { title: title ?? null })
export const getChat = (api: ApiClient, id: string) =>
  api.get<ChatDetailOut>(`/chats/${id}`)
```

`frontend/src/chat/useChats.ts`:
```ts
import { useCallback, useEffect, useState } from 'react'
import { useApiClient } from '../auth/AuthContext'
import type { ChatOut } from '../api/types'
import { createChat, listChats } from './chatApi'

export function useChats() {
  const api = useApiClient()
  const [chats, setChats] = useState<ChatOut[]>([])
  const [loading, setLoading] = useState(true)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      setChats(await listChats(api))
    } finally {
      setLoading(false)
    }
  }, [api])

  useEffect(() => {
    void reload()
  }, [reload])

  const newChat = useCallback(async () => {
    const chat = await createChat(api)
    setChats((prev) => [chat, ...prev])
    return chat
  }, [api])

  return { chats, loading, reload, newChat }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- useChats`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/chat/chatApi.ts frontend/src/chat/useChats.ts frontend/src/chat/useChats.test.tsx
git commit -m "feat(frontend): chat list hook and chat API calls"
```

---

### Task 9: useChatStream hook (send + stream tokens)

**Files:**
- Create: `frontend/src/chat/useChatStream.ts`
- Test: `frontend/src/chat/useChatStream.test.tsx`

**Interfaces:**
- Consumes: `useApiClient` (Task 5), `parseSse` (Task 4), `getChat` (Task 8), `MessageOut` (Task 3).
- Produces: `type ChatMessage = { id: string; role: 'user' | 'assistant'; content: string; streaming: boolean; error?: boolean }`; `useChatStream(chatId: string | null): { messages: ChatMessage[]; sending: boolean; send(text: string): Promise<void>; loadHistory(): Promise<void> }`. `send` appends a user message + a streaming assistant message, POSTs via `api.stream`, feeds the body through `parseSse`, appends each `delta.text` to the assistant message, flips `streaming` off on `done`, and sets `error` on an `error` event or thrown failure.

- [ ] **Step 1: Write the failing test**

`frontend/src/chat/useChatStream.test.tsx`:
```tsx
import { renderHook, act, waitFor } from '@testing-library/react'
import { server, http, HttpResponse } from '../test/msw'
import { AuthProvider } from '../auth/AuthContext'
import { useChatStream } from './useChatStream'

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <AuthProvider>{children}</AuthProvider>
)
beforeEach(() =>
  localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'r' })),
)

test('streams assistant deltas into a message', async () => {
  server.use(
    http.post('/api/chats/c1/messages', () => {
      const body =
        'event: delta\ndata: {"text":"Привет"}\n\n' +
        'event: delta\ndata: {"text":", Роман"}\n\n' +
        'event: done\ndata: {"message_id":"m9"}\n\n'
      return new HttpResponse(body, {
        headers: { 'Content-Type': 'text/event-stream' },
      })
    }),
  )
  const { result } = renderHook(() => useChatStream('c1'), { wrapper })
  await act(async () => {
    await result.current.send('Привет')
  })
  await waitFor(() => expect(result.current.sending).toBe(false))
  const assistant = result.current.messages.find((m) => m.role === 'assistant')!
  expect(assistant.content).toBe('Привет, Роман')
  expect(assistant.streaming).toBe(false)
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- useChatStream`
Expected: FAIL — cannot find `./useChatStream`.

- [ ] **Step 3: Implement the hook**

`frontend/src/chat/useChatStream.ts`:
```ts
import { useCallback, useState } from 'react'
import { useApiClient } from '../auth/AuthContext'
import { parseSse } from '../api/sse'
import { getChat } from './chatApi'

export type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  streaming: boolean
  error?: boolean
}

let counter = 0
const localId = () => `local-${counter++}`

export function useChatStream(chatId: string | null) {
  const api = useApiClient()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [sending, setSending] = useState(false)

  const loadHistory = useCallback(async () => {
    if (!chatId) {
      setMessages([])
      return
    }
    const detail = await getChat(api, chatId)
    setMessages(
      detail.messages.map((m) => ({
        id: m.id,
        role: m.role === 'user' ? 'user' : 'assistant',
        content: m.content,
        streaming: false,
      })),
    )
  }, [api, chatId])

  const send = useCallback(
    async (text: string) => {
      if (!chatId) return
      const assistantId = localId()
      setMessages((prev) => [
        ...prev,
        { id: localId(), role: 'user', content: text, streaming: false },
        { id: assistantId, role: 'assistant', content: '', streaming: true },
      ])
      const patch = (fn: (m: ChatMessage) => ChatMessage) =>
        setMessages((prev) => prev.map((m) => (m.id === assistantId ? fn(m) : m)))
      setSending(true)
      try {
        const res = await api.stream(`/chats/${chatId}/messages`, { content: text })
        if (!res.body) throw new Error('no stream')
        for await (const ev of parseSse(res.body)) {
          if (ev.event === 'delta') {
            const { text: delta } = JSON.parse(ev.data) as { text: string }
            patch((m) => ({ ...m, content: m.content + delta }))
          } else if (ev.event === 'done') {
            patch((m) => ({ ...m, streaming: false }))
          } else if (ev.event === 'error') {
            const { message } = JSON.parse(ev.data) as { message: string }
            patch((m) => ({ ...m, streaming: false, error: true, content: message }))
          }
        }
      } catch {
        patch((m) => ({
          ...m,
          streaming: false,
          error: true,
          content: 'Ошибка при получении ответа.',
        }))
      } finally {
        setSending(false)
      }
    },
    [api, chatId],
  )

  return { messages, sending, send, loadHistory }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- useChatStream`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/chat/useChatStream.ts frontend/src/chat/useChatStream.test.tsx
git commit -m "feat(frontend): streaming chat turn hook consuming SSE deltas"
```

---

### Task 10: Presentational components — Sidebar, Composer, Message

**Files:**
- Create: `frontend/src/components/Sidebar.tsx`, `frontend/src/components/Sidebar.module.css`, `frontend/src/components/ChatListItem.tsx`, `frontend/src/components/UserCard.tsx`, `frontend/src/components/Composer.tsx`, `frontend/src/components/Composer.module.css`, `frontend/src/components/Message.tsx`, `frontend/src/components/Message.module.css`
- Test: `frontend/src/components/Sidebar.test.tsx`, `frontend/src/components/Composer.test.tsx`

**Interfaces:**
- Consumes: `CapyLogo` (Task 2), `useAuth` (Task 5), `ChatOut` (Task 3), `ChatMessage` (Task 9), lucide-react icons (`Plus`, `Search`, `Settings`, `Brain`, `Clock`, `LogOut`, `ChevronUp`, `Paperclip`, `ArrowUp`).
- Produces:
  - `Sidebar(props: { chats: ChatOut[]; activeChatId: string | null; onSelect(id): void; onNewChat(): void })` — logo lockup, New-chat button, search input (client-side filter over `chats` by title), grouped list via `ChatListItem`, a bottom block with **disabled** rows Память / Задачи (badge «2») / Настройки (`aria-disabled`, non-interactive), and `UserCard`.
  - `ChatListItem(props: { chat: ChatOut; active: boolean; onSelect(): void })`.
  - `UserCard()` — reads `useAuth().user`; avatar initial, name, «локально», chevron; click toggles a popover with «Выйти из профиля» → `useAuth().logout()`.
  - `Composer(props: { onSend(text): void; disabled?: boolean })` — textarea (auto-grow) + paperclip (visual only) + send button; Enter (no Shift) or send-button submits non-empty, then clears.
  - `Message(props: { message: ChatMessage })` — user bubble (right) or assistant row (glyph + text); while `streaming`, render the blinking caret span (`animation:blink 1s steps(1) infinite`, styles from `CapybaraAgent.dc.html:294`); `error` messages get an error style.

All visual values ported from README §1 (Sidebar), §3 (composer, bubbles, caret). Icons: swap the prototype's inline SVGs for the lucide-react equivalents named above.

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/Sidebar.test.tsx`:
```tsx
import { render, screen } from '@testing-library/react'
import { AuthProvider } from '../auth/AuthContext'
import { Sidebar } from './Sidebar'

beforeEach(() =>
  localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'roman' })),
)

test('deferred nav items are disabled', () => {
  render(
    <AuthProvider>
      <Sidebar chats={[]} activeChatId={null} onSelect={() => {}} onNewChat={() => {}} />
    </AuthProvider>,
  )
  for (const label of ['Память', 'Фоновые задачи', 'Настройки']) {
    expect(screen.getByText(label).closest('[aria-disabled="true"]')).not.toBeNull()
  }
})
```

`frontend/src/components/Composer.test.tsx`:
```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Composer } from './Composer'

test('submits on Enter and clears', async () => {
  const onSend = vi.fn()
  render(<Composer onSend={onSend} />)
  const box = screen.getByRole('textbox')
  await userEvent.type(box, 'Привет{Enter}')
  expect(onSend).toHaveBeenCalledWith('Привет')
  expect(box).toHaveValue('')
})

test('does not submit empty input', async () => {
  const onSend = vi.fn()
  render(<Composer onSend={onSend} />)
  await userEvent.type(screen.getByRole('textbox'), '{Enter}')
  expect(onSend).not.toHaveBeenCalled()
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm run test -- Sidebar Composer`
Expected: FAIL — modules not found.

- [ ] **Step 3: Implement the components**

Implement all files listed under **Files**. `Composer` logic (copy verbatim; styling in `Composer.module.css` from README §3 composer):
```tsx
import { useRef, useState, type KeyboardEvent } from 'react'
import { ArrowUp, Paperclip } from 'lucide-react'
import styles from './Composer.module.css'

export function Composer({ onSend, disabled }: { onSend: (t: string) => void; disabled?: boolean }) {
  const [value, setValue] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)

  function submit() {
    const text = value.trim()
    if (!text || disabled) return
    onSend(text)
    setValue('')
    if (ref.current) ref.current.style.height = 'auto'
  }
  function onKeyDown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }
  return (
    <div className={styles.composer}>
      <textarea
        ref={ref}
        className={styles.input}
        value={value}
        rows={1}
        placeholder="Спросите что-нибудь…"
        onChange={(e) => {
          setValue(e.target.value)
          e.target.style.height = 'auto'
          e.target.style.height = `${e.target.scrollHeight}px`
        }}
        onKeyDown={onKeyDown}
      />
      <div className={styles.row}>
        <button type="button" className={styles.iconBtn} aria-label="Прикрепить">
          <Paperclip size={18} />
        </button>
        <div className={styles.spacer} />
        <button type="button" className={styles.send} aria-label="Отправить" onClick={submit}>
          <ArrowUp size={18} />
        </button>
      </div>
    </div>
  )
}
```
For `Sidebar`, render the three deferred rows as `<div aria-disabled="true" className={styles.navDisabled}>` wrapping the icon + label (Память, «Фоновые задачи» with a «2» badge, Настройки) so they are visible but inert. `Message` renders the caret span only when `message.streaming` is true.

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm run test -- Sidebar Composer`
Expected: PASS (all three tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components
git commit -m "feat(frontend): sidebar, composer, and message components"
```

---

### Task 11: ChatScreen — welcome + active, wired end to end

**Files:**
- Create: `frontend/src/screens/ChatScreen.tsx`, `frontend/src/screens/ChatScreen.module.css`
- Test: `frontend/src/screens/ChatScreen.test.tsx`
- Modify: `frontend/src/App.tsx` (replace the `<div>chat</div>` placeholder with `<ChatScreen />`)

**Interfaces:**
- Consumes: `Sidebar`, `Composer`, `Message` (Task 10), `useChats` (Task 8), `useChatStream` (Task 9), `CapyLogo` (Task 2), `useAuth` (Task 5).
- Produces: `ChatScreen(): JSX.Element`. Holds `activeChatId: string | null`. When null → **welcome** (glyph, greeting «Чем помочь, {name}?», Composer, prompt chips). When set → **active**: header (chat title) + thread of `Message` + Composer. Selecting a chat loads history (`useChatStream(activeChatId).loadHistory` in an effect on `activeChatId`). Sending from welcome first creates a chat (`useChats().newChat()`), sets it active, then sends; sending from active calls `send`. After the first send in a chat, calls `useChats().reload()`.

- [ ] **Step 1: Write the failing test**

`frontend/src/screens/ChatScreen.test.tsx`:
```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, http, HttpResponse } from '../test/msw'
import { AuthProvider } from '../auth/AuthContext'
import { ChatScreen } from './ChatScreen'

beforeEach(() =>
  localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'roman' })),
)

test('welcome greets the user and streams a reply after sending', async () => {
  const chat = { id: 'c1', title: 'Новый чат', created_at: '', updated_at: '' }
  server.use(
    http.get('/api/chats', () => HttpResponse.json([])),
    http.post('/api/chats', () => HttpResponse.json(chat, { status: 201 })),
    http.post('/api/chats/c1/messages', () =>
      new HttpResponse('event: delta\ndata: {"text":"Здравствуйте"}\n\nevent: done\ndata: {"message_id":"m1"}\n\n', {
        headers: { 'Content-Type': 'text/event-stream' },
      }),
    ),
  )
  render(
    <AuthProvider>
      <ChatScreen />
    </AuthProvider>,
  )
  expect(await screen.findByText(/Чем помочь, roman/)).toBeInTheDocument()
  await userEvent.type(screen.getByRole('textbox'), 'Привет{Enter}')
  expect(await screen.findByText('Здравствуйте')).toBeInTheDocument()
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- ChatScreen`
Expected: FAIL — cannot find `./ChatScreen`.

- [ ] **Step 3: Implement ChatScreen**

Implement `ChatScreen.tsx` composing `Sidebar` + main area. Welcome greeting uses `useAuth().user?.displayName`. Send handler:
```tsx
async function handleSend(text: string) {
  let id = activeChatId
  if (!id) {
    const chat = await newChat()
    id = chat.id
    setActiveChatId(id)
  }
  await send(text)
  await reload()
}
```
Wire `useChatStream(activeChatId)` and re-run `loadHistory()` in a `useEffect` keyed on `activeChatId`. Prompt chips: 4 pills whose click sets the composer text (lift composer value via a `key`-reset or a shared state — simplest: pass an `initialText` prop to `Composer` and remount on chip click via `key`). Styling from README §2 (welcome) and §3 (active thread + header). Then update `App.tsx`:
```tsx
// replace <div>chat</div> with:
import { ChatScreen } from './screens/ChatScreen'
// ...
{token ? <ChatScreen /> : <AuthScreen />}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- ChatScreen App`
Expected: PASS.

- [ ] **Step 5: Full suite + typecheck + build**

Run: `npm run test && npm run typecheck && npm run lint && npm run build`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/screens/ChatScreen.tsx frontend/src/screens/ChatScreen.module.css frontend/src/screens/ChatScreen.test.tsx frontend/src/App.tsx
git commit -m "feat(frontend): chat screen with welcome and streaming active thread"
```

---

### Task 12: Production Docker serving (nginx) + compose service

**Files:**
- Create: `frontend/Dockerfile`, `frontend/nginx.conf`
- Modify: `docker-compose.yml` (repo root — add a `frontend` service)

**Interfaces:**
- Produces: a multi-stage image that builds the Vite app and serves `dist/` via nginx, proxying `/api/` to the `api` service. Same `/api` contract as the dev proxy, so no app code changes.

- [ ] **Step 1: Inspect the existing compose file**

Run (from repo root): `cat docker-compose.yml`
Note the `api` service name and the port it listens on (assume `api` on `8000`; adjust the proxy target below to match what you find).

- [ ] **Step 2: Create `frontend/nginx.conf`**

```nginx
server {
  listen 80;
  root /usr/share/nginx/html;
  index index.html;

  location /api/ {
    proxy_pass http://api:8000/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_buffering off;                 # required so SSE streams flush
    proxy_set_header Connection '';
    proxy_read_timeout 3600s;
  }

  location / {
    try_files $uri $uri/ /index.html;    # SPA fallback
  }
}
```
Note: `proxy_pass http://api:8000/;` with the trailing `/` strips the `/api` prefix, matching the dev proxy's `rewrite`.

- [ ] **Step 3: Create `frontend/Dockerfile`**

```dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
```

- [ ] **Step 4: Add the compose service**

Add to `docker-compose.yml` `services:` (match indentation of the existing file):
```yaml
  frontend:
    build: ./frontend
    ports:
      - "3000:80"
    depends_on:
      - api
```

- [ ] **Step 5: Verify the build**

Run (from repo root): `docker compose build frontend`
Expected: image builds successfully (Vite build + nginx copy).

- [ ] **Step 6: Commit**

```bash
git add frontend/Dockerfile frontend/nginx.conf docker-compose.yml
git commit -m "chore(frontend): nginx production image and compose service proxying /api"
```

---

### Task 13: Frontend README

**Files:**
- Create: `frontend/README.md`

- [ ] **Step 1: Write the README**

Document: prerequisites (Node 20 via nvm); `npm install`; `npm run dev` (needs the backend on `localhost:8000`; Vite proxies `/api`); `npm run test`, `npm run lint`, `npm run typecheck`, `npm run build`; the layered architecture (one line per folder from the plan's File Structure); and the Docker path (`docker compose up frontend`, served on `:3000`). State the slice scope: auth + chat only; Память/Задачи/Настройки are intentionally disabled placeholders.

- [ ] **Step 2: Commit**

```bash
git add frontend/README.md
git commit -m "docs(frontend): README with dev, test, and Docker instructions"
```

---

## Self-Review notes

- **Spec coverage:** auth screen (T6), sidebar + list + user card + logout (T10), welcome (T11), active streaming (T9+T11), disabled deferred nav (T10), same-origin `/api` no-CORS (T1 dev proxy + T12 nginx), SSE via fetch not EventSource (T4+T9), localStorage token + 401 auto-logout (T3+T5), TDD with MSW (all tasks), theme/tokens/background/CapyLogo (T2), Docker serving (T12), README (T13). All §9 deliverables mapped.
- **Type consistency:** `ApiClient` (`get`/`post`/`stream`) is defined in T3 and consumed unchanged in T5/T8/T9; `ChatMessage` defined in T9 and consumed in T10/T11; `useAuth`/`useApiClient` defined in T5 and used consistently thereafter; `parseSse` signature (T4) matches its use in T9.
- **Deferred by design (not gaps):** attachments, tool-call blocks, citations, code/artifact panels, settings/wizards/exec-detail — all out of scope per the spec.
