# CapybaraAgent — Frontend

React + TypeScript + Vite single-page app. Talks to the Python backend over same-origin `/api`.

---

## Prerequisites

- **Node 20+** (use [nvm](https://github.com/nvm-sh/nvm): `nvm use 20`)
- **Backend running on `localhost:8000`** — required for `npm run dev` (Vite proxies `/api` → `http://localhost:8000`)

---

## Setup

```bash
npm install
```

---

## Scripts

| Command             | What it does                                |
| ------------------- | ------------------------------------------- |
| `npm run dev`       | Start dev server with Vite proxy on `:5173` |
| `npm run build`     | Type-check then compile to `dist/`          |
| `npm run test`      | Run Vitest test suite (single pass)         |
| `npm run lint`      | ESLint with zero-warning policy             |
| `npm run typecheck` | TypeScript type-check without emitting      |
| `npm run preview`   | Serve the production build locally          |

---

## Architecture

```
src/
  api/          ApiClient (get/post/stream), SSE parser, shared API types
  auth/         AuthContext + useAuth hook, localStorage token storage
  chat/         Chat API calls, useChatStream (SSE streaming), useChats hook
  components/   Shared UI: BackgroundGlow, CapyLogo, ChatListItem, Composer, Message, Sidebar, UserCard
  screens/      Top-level page components: AuthScreen (login/register), ChatScreen
  theme/        CSS custom-property tokens and global base styles
```

---

## Networking

All API calls use same-origin `/api` paths — no CORS needed.

- **Dev:** Vite rewrites `/api/*` → `http://localhost:8000/*` (see `vite.config.ts`)
- **Prod:** nginx (`nginx.conf`) proxies `/api/` → the `api` Docker service, with `proxy_buffering off` so SSE streams flush correctly

---

## Docker

```bash
# Frontend only (expects `api` service already up)
docker compose up frontend

# Full stack
docker compose up
```

The built SPA is served by nginx on **port 3000** (`http://localhost:3000`), which proxies `/api` to the `api` service.

---

## Slice scope

This slice covers **auth** (login / register) and **chat** (list chats, welcome screen, streaming replies via SSE).

The sidebar items **Память**, **Фоновые задачи**, and **Настройки** are intentionally rendered as disabled placeholders — their backends don't exist yet and will be enabled in a future slice.
