# Chat management (favorites, delete, rename, auto-title) — design

**Date:** 2026-07-04
**Status:** approved (brainstorm)

## Problem

The sidebar lists chats but offers no management: you cannot favorite, rename, or delete a
chat, and every new chat keeps the default title "Новый чат" until you never rename it.
The updated design handoff (`design/CapybaraAgent.dc.html`) adds a favorites group, a
per-chat context menu (rename / favorite / delete), and inline rename. Separately, we want
Claude-style automatic chat titles from the first message.

## Goal

Ship a cohesive "chat management" slice: favorite (star) chats with a pinned group, delete
chats, rename chats, and auto-generate a chat title from the first message via the LLM.
Follow the design's layout/behaviour/colours/logo, but replace its icons with proper
`lucide-react` icons (star for favorites, etc.).

## Scope

In scope: `chats.is_favorite` column + migration; a unified `PATCH /chats/{id}`
(title / model / is_favorite); `DELETE /chats/{id}`; LLM auto-title on the first turn
delivered via a new SSE `title` event; sidebar favorites group, per-chat star toggle,
context menu (rename/favorite/delete), inline rename, delete confirmation; icon + logo
polish. Backend + frontend + tests.

Out of scope (next stage): the Memory / Tasks / Settings sidebar panels, the system-status
alerts panel. Chat search already exists (client-side filter in `Sidebar`) and date
grouping already exists — neither is rebuilt here.

## Decisions

- **Favorite, not "pin".** The design mixes "pin"/"star"; we standardise on **favorite**
  with a filled `Star` icon and an "Избранное" group at the top.
- **One PATCH for all mutable chat fields.** `title`, `model`, `is_favorite` all go through
  `PATCH /chats/{id}`; `model` is validated only when present, so rename and favorite never
  touch model validation.
- **Auto-title is LLM-generated** (chosen over truncation/hybrid), from the first user
  message, and must not delay the answer.
- **Grouping is client-side.** `GET /chats` is unchanged; the sidebar splits favorites from
  the existing date buckets.

## Backend

### Data & migration

- Add `chats.is_favorite BOOLEAN NOT NULL DEFAULT false` (new Alembic revision, chained on
  `b2d0cafe0002`).
- `Chat.is_favorite: Mapped[bool]` (default `False`).
- `ChatOut` gains `is_favorite: bool`.

### `PATCH /chats/{id}` — unified update

- `ChatUpdate` becomes `{ title?: str(1..200), model?: str(1..128), is_favorite?: bool }`
  with a validator requiring **at least one** field present (else 422).
- The endpoint applies each provided field via `ChatRepo.update`. `model`, if provided, is
  validated with `ensure_available` first (409 unavailable / 502 provider down — unchanged).
  `title` / `is_favorite` need no external validation.
- Returns the updated `ChatOut`. Ownership via `get_owned_chat` (404 if not owned).

### `DELETE /chats/{id}`

- `get_owned_chat` → `ChatRepo.delete(chat)` → `204 No Content`. The `Chat.messages`
  relationship already cascades (`all, delete-orphan`), so messages are removed with it.

### Auto-title (LLM)

- `BaseAgent.generate_title(model_name: str, first_user_message: str) -> str`: a one-shot
  LLM call (separate from the chat run) with a system prompt asking for a concise 3–5 word
  title in the message's language, no surrounding quotes. The result is stripped of quotes,
  collapsed to one line, and truncated to the `title` column bound (200). On error or empty
  output it falls back to a truncation of `first_user_message` — the title is always at
  least as good as the default.
- **Trigger:** only on the **first turn** of a chat (history empty at `begin_turn`) **and**
  when the chat's title is still the default (`"Новый чат"`). A manually-set or already
  auto-set title is never overwritten.
- **Delivery:** the message stream proceeds normally (`delta` … `done`). *After* `done`, if
  the trigger holds, the service generates the title, persists it to `chat.title`, emits a
  new **`event: title` / `data: {"title": "<title>"}`** frame, then closes the stream. The
  answer is never delayed by title generation.
- Failure isolation: a title-generation failure is swallowed (logged) and simply yields no
  `title` event — it must never break the reply stream.

## Frontend

### Types & API

- `ChatOut.is_favorite: boolean`.
- `chatApi.ts`: `deleteChat(api, id)` (DELETE); reuse `api.patch` for
  `renameChat(api, id, title)` and `setFavorite(api, id, isFavorite)`.
- `useChatStream` handles the new `event: title`: parses `{title}` and invokes an
  `onTitle(chatId, title)` callback so the active chat's title updates immediately (no wait
  for a list reload).

### Components

- **ChatListItem** (design layout, lucide icons): left — a `Star` toggle (filled when
  favorite) calling `setFavorite`; centre — the title, replaced by an inline `<input>` in
  rename mode (Enter commits, Esc/blur cancels); right — a `MoreHorizontal` button opening
  the context menu.
- **Context menu**: `Rename` (`Pencil`), "В избранное"/"Убрать из избранного" (`Star`),
  `Delete` (`Trash2`, red). Positioned by the trigger, closes on outside click. Delete asks
  a light confirmation (a second "Точно?" click or a small confirm) before firing.
- **Sidebar**: a top **"Избранное"** group (star in the group header) holding all
  `is_favorite` chats, then the existing date groups (Сегодня/Вчера/Ранее) with favorites
  excluded. The existing search filter still applies before grouping.
- **ChatScreen**: passes `onRename` / `onToggleFavorite` / `onDelete` / menu-open state;
  updates local state optimistically then `reload()`s. Deleting the active chat returns to
  the welcome state. Wires `onTitle` from `useChatStream` to update the chat title live.
- **Icons/logo**: new UI uses only `lucide-react` (`Star`, `Trash2`, `Pencil`,
  `MoreHorizontal`); the sidebar logo lockup adopts the design's new mark (`capy_mark.png`).

## Testing (TDD)

- Backend: migration up/down; `PATCH` with title-only, is_favorite-only, model-only, and
  partial combos, plus the at-least-one-field 422; `DELETE` returns 204 and removes the chat
  + its messages; `generate_title` (mocked LLM) returns a cleaned title and falls back on
  failure; the send flow emits an SSE `title` event on the first turn only (not on later
  turns, not when the title is already custom).
- Frontend: msw mocks for delete/patch; ChatListItem renders the star (filled/empty) and
  menu; rename input commits/cancels; the "Избранное" group renders favorites on top;
  `useChatStream` updates the title on a `title` event; deleting the active chat returns to
  welcome.
