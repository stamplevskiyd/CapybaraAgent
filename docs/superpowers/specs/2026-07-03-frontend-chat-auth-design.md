# Frontend slice: chat + auth (design)

Date: 2026-07-03
Branch: `feature/frontend-chat-auth`
Status: design approved, pending spec review

## 1. Purpose & scope

Build the first **frontend** slice for CapybaraAgent: a web SPA that talks to the
existing chat-core backend over HTTP/SSE. It covers exactly the backend surface that
exists today and nothing more.

**In scope (wired to the real backend):**
- **Auth screen** — login and register modes (device-local profiles).
- **Sidebar** — logo lockup, "New chat", search (client-side filter over the loaded
  list), grouped chat list, user card with logout popover.
- **Chat — welcome** (empty state): capybara glyph, greeting, composer, prompt chips.
- **Chat — active**: user/assistant message bubbles, **live token streaming via SSE**
  (blinking caret while streaming), error surfacing in-thread.

**Deferred (no backend yet — shown but non-functional):**
- Sidebar rows **Память / Задачи / Настройки** render **visible but disabled**
  ("coming soon"), preserving the design's look without dead-end navigation.
- Settings screens, MCP/LLM connect wizards, artifact panel, exec-detail modal,
  attachments, tool-call blocks, citations, code artifacts — **not built** this slice.
  They belong to their own future slices when the backends exist.

**Explicitly out of scope:** any backend change (no CORS work — see §4), real LLM calls
in tests, packaging as a native desktop app (product is always a Dockerized web service).

The UI is recreated pixel-faithfully from `design_handoff_capybaraagent/README.md`
tokens and `CapybaraAgent.dc.html`; on any conflict, the README tokens win.

## 2. Backend surface consumed

Existing endpoints (branch `feature/chat-core-backend`, not yet merged to `main`):

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/users` | Register `{display_name, username, password}` → `UserOut` (201; 409 if taken) |
| `POST` | `/auth/login` | `{username, password}` → `{access_token, token_type}` (401 on bad creds) |
| `GET` | `/chats` | List chats for current user (most-recently-updated first) |
| `POST` | `/chats` | Create chat `{title?}` → `ChatOut` (201) |
| `GET` | `/chats/{id}` | Chat + full message history (`ChatDetailOut`) |
| `POST` | `/chats/{id}/messages` | `{content}` → **SSE** stream of `delta` / `done` / `error` |
| `GET` | `/health` | Liveness |

Auth is **stateless JWT**: send `Authorization: Bearer <token>`; logout = client discards
the token. There is **no** `GET /users/me` endpoint — the frontend derives the displayed
user from what it knows locally (see §6).

SSE event shapes (from `chats.py`):
- `event: delta`  `data: {"text": "..."}`
- `event: done`   `data: {"message_id": "...", "usage": {...}}`
- `event: error`  `data: {"message": "..."}`

## 3. Stack

- **React 18 + TypeScript**, built with **Vite**. Node 20 LTS.
- **CSS Modules** for component styles (scoped, zero-runtime), plus a global
  `tokens.css` holding design tokens as CSS custom properties (`--accent`, glass
  backgrounds, text colors, radii, shadows). Fonts: Space Grotesk, Hanken Grotesk,
  JetBrains Mono. Icons: **lucide-react**.
- **State:** React Context + hooks. No Redux/zustand/react-router this slice (only two
  top-level views). TanStack Query is a likely *future* addition when server-state grows
  (settings/memory/tasks) — not now (YAGNI).
- **Tooling:** ESLint + Prettier (frontend-local), TypeScript strict.
- **Tests:** Vitest + React Testing Library + MSW (mock API and SSE). TDD.
- Lives in **`frontend/`** at the repo root with its own `package.json`, isolated from
  the Python backend in `src/`.

## 4. Networking & CORS

The backend has **no CORS configured**, and we add none. Instead the browser always talks
to the **same origin**, which proxies `/api/*` to the FastAPI service:

- **Dev:** Vite dev-server proxy — `/api` → `http://localhost:8000`.
- **Prod (Docker):** a `frontend` container (nginx) serves the static build **and**
  proxies `/api` → the `api` service. Added to `docker-compose` as a new service.

The `apiClient` uses base path `/api`, so the same code works in both.

## 5. Architecture (layered, explicit boundaries — mirrors backend discipline)

```
frontend/src/
  api/
    client.ts        # fetch wrapper: base '/api', injects Bearer, JSON, error mapping
    sse.ts           # parse a fetch ReadableStream into typed SSE events
    types.ts         # response types mirroring backend schemas
  auth/
    AuthContext.tsx  # { token, user, login, register, logout }; persists token
    storage.ts       # localStorage read/write of token (+ cached display data)
  chat/
    useChats.ts      # list + create chats
    useChatStream.ts # send message, consume SSE, expose growing assistant text
  components/         # presentational, dumb: Sidebar, Composer, Message, ChatListItem,
                      # UserCard, CapyLogo, Icon wrappers, BackgroundGlow, ...
  screens/
    AuthScreen.tsx    # login/register modes
    ChatScreen.tsx    # sidebar + main (welcome | active)
  theme/
    tokens.css        # CSS variables (colors, glass, radii, shadows)
    global.css        # resets, fonts, background wallpaper + drifting glows
  App.tsx             # view = 'auth' | 'chat'; picks screen from auth state
  main.tsx
```

Each unit has one purpose and a defined interface: `apiClient` knows HTTP but not React;
hooks (`useChats`, `useChatStream`) own data/effects; components are presentational and
take props; screens compose them. This keeps files small and independently testable.

## 6. Data flow

**Auth.** `AuthContext` holds `{ token, user }`. On login/register it calls the API,
stores the token in `localStorage`, and sets `view='chat'`. Since there's no
`GET /users/me`: register returns `UserOut` (use it directly); login returns only a token,
so we cache the entered `username` alongside the token and show that (display name falls
back to username until a profile endpoint exists — noted as a future refinement). `logout`
clears storage and returns to `view='auth'`. A `401` from any API call triggers auto-logout.

**Chat list.** `useChats` loads `GET /chats` on entering the chat view; "New chat" calls
`POST /chats` and selects the result (welcome state). Search filters the loaded list
client-side. Date grouping (Сегодня/Вчера/Ранее) is computed from `updated_at`.

**Streaming a turn.** On send:
1. Optimistically append the user bubble and an empty assistant bubble (`streaming:true`).
2. `POST /chats/{id}/messages` via `fetch`; read `response.body` as a stream.
3. `sse.ts` yields typed events; each `delta` appends `text` to the assistant bubble
   (blinking caret shown while streaming); `done` marks it complete (caret off) and
   records `message_id`; `error` replaces the caret with an in-thread error + retry.
4. On first message in a fresh chat, refresh the sidebar list (title/updated_at may change).

`EventSource` is **not** used (it can't POST or set headers); we parse SSE from the fetch
stream manually.

## 7. Error handling & edge cases

- Invalid login/register → inline message under the form (401 / 409 mapped to friendly text).
- `401` mid-session on any request → clear token, bounce to auth screen.
- Stream network failure or `error` event → error row in thread + a retry affordance;
  never a silently broken bubble.
- Empty chat list → welcome screen.
- Reduced motion → background glow / caret animations paused (respect `prefers-reduced-motion`).

## 8. Testing (TDD — tests first)

Using Vitest + RTL + MSW:
- `sse.ts` — parses multi-event streams, partial chunks, `delta`/`done`/`error`, unicode.
- `AuthContext` — login stores token; logout clears it; token persists across reloads;
  401 triggers logout.
- `useChatStream` — appends deltas in order, flips streaming off on done, surfaces error.
- `ChatScreen` render — streaming caret appears then disappears; user+assistant bubbles.
- `Sidebar` — Память/Задачи/Настройки render disabled; New chat / logout wired.
No real backend or LLM is contacted; MSW mocks HTTP and the SSE byte stream.

## 9. Deliverables

1. `frontend/` scaffold: Vite + React + TS, ESLint/Prettier, Vitest, `package.json`.
2. Theme layer: `tokens.css` + `global.css` (background wallpaper, fonts, glass).
3. `api/` (client, sse, types) with tests.
4. `auth/` (context, storage) + `AuthScreen`, with tests.
5. `chat/` hooks + `ChatScreen` (sidebar, welcome, active/streaming) + components, tests.
6. Vite dev proxy config; `frontend/Dockerfile` (nginx) + `docker-compose` `frontend`
   service proxying `/api`.
7. Short `frontend/README.md`: how to run dev, test, build.

## 10. Success criteria

- `npm run dev` + running backend: register → land in chat → create chat → send a
  message → see tokens stream in with a caret → reply persists on reload.
- Logout returns to auth; refresh keeps the session (token persisted).
- Deferred sidebar items are visibly disabled; no route leads to an unbuilt screen.
- `npm run lint`, `npm run test`, `tsc --noEmit`, and `npm run build` all pass.
- UI matches the handoff tokens (colors, glass, typography, radii, spacing).
