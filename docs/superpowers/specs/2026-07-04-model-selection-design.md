# Model selection & display — design

**Date:** 2026-07-04
**Status:** approved (brainstorm)

## Problem

The LLM model is hard-wired to `settings.default_model` in the app lifespan. There is no
way to see which models are actually installed in Ollama, and no way to choose one. When
the configured model is absent from Ollama, the stream fails deep inside the run and the UI
only sees an opaque `event: error / {"message": "Internal server error while streaming the
reply"}`, giving the user no idea the real cause is a missing model.

## Goal

Show the real list of available models (Ollama only, for now) and let the user pick one
**per chat**, with the selector living in the composer's bottom row next to the paperclip.
No implicit fallback: if a chat has no model selected, or its selected model is no longer
installed, sending is blocked and the user is prompted to choose.

## Scope

In scope: Ollama model listing, per-chat model selection, composer selector, up-front
validation with a clear error, one DB column + migration, backend + frontend + tests.

Out of scope: other providers (OpenAI/OpenRouter), per-message model switching, model
metadata beyond the name, caching of the model list, global app-level model setting.

> Slice note: the active Slice 1 is "backend chat core" and the frontend was nominally the
> next slice. This feature deliberately spans backend + frontend together, at the user's
> direction. Recorded here as an intentional deviation, not an oversight.

## Decisions

- **Selection lives per-chat.** The model is chat state, stored on the chat row. The
  composer selector edits it.
- **Change mechanism:** a dedicated `PATCH /chats/{id}` with `{model}`. Sending a message
  carries no model — the backend reads `chat.model`. For a brand-new chat (not yet
  persisted), the choice is held client-side and passed to `POST /chats`.
- **No fallback.** `chat.model = NULL` or a model missing from the current Ollama list
  means "not selected" → the selector is highlighted and send is disabled (client-side),
  and the backend rejects the turn up front (defense in depth). `settings.default_model`
  is no longer a server-side fallback; it survives only as an optional client hint for the
  initial selection.

## Backend

### Provider abstraction

`BaseAgent` no longer binds a single model at construction. It gains:

```python
class BaseAgent(ABC):
    @abstractmethod
    async def list_models(self) -> list[str]: ...
    @abstractmethod
    def _build_model(self, name: str) -> Model: ...
    async def stream_reply(self, model_name, user_content, history, acc): ...  # +model_name
```

`OllamaAgent`:
- `list_models()` — `GET {ollama_base_url}/api/tags` via `httpx.AsyncClient`; extract the
  `name` of each entry (e.g. `llama3.1:8b`, `qwen2.5:14b`).
- `_build_model(name)` — the same `OpenAIChatModel(name, provider=OpenAIProvider(...))`,
  but the model name is supplied per-turn. Built per call (pydantic-ai `Agent` is cheap).
- `stream_reply` builds the model for `model_name` and streams as today; the actual model
  from the response is still recorded into `messages.model`.

### Endpoints (all under existing bearer auth)

- **`GET /models`** → `{"provider": "ollama", "models": ["llama3.1:8b", ...]}`.
  If Ollama is unreachable → `502` with a clear message (`Ollama unreachable at <url>`),
  not a generic 500.
- **`PATCH /chats/{id}`** → body `{"model": "llama3.1:8b"}`. Validates the model is in
  `list_models()`, writes `chat.model`, returns `ChatOut`. Unknown model → `409` with a
  clear message.
- **`POST /chats`** — `ChatCreate` gains an optional `model` field.
- `ChatOut` / `ChatDetailOut` gain `model: str | None`.

### DB & migration

Add a nullable `chats.model` column (`String(128)`, `NULL` = not selected). New Alembic
revision.

### Validation & error flow (the core fix)

- `ChatService.begin_turn` already loads the chat on a short-lived session. Add: if
  `chat.model` is `NULL` **or** absent from `agent.list_models()`, raise a new
  `ModelUnavailableError`.
- `send_message` runs `begin_turn` **before** opening the `StreamingResponse`. It maps
  `ChatNotFoundError → 404` and `ModelUnavailableError → 409` (JSON, before any SSE bytes),
  with a message like `Model '<name>' is not available. Select an installed model.` The
  client sees a normal HTTP status instead of an opaque in-stream error.

## Frontend

- **Composer bottom row:** a compact model dropdown next to the paperclip
  (`lucide-react` `ChevronDown` + list). Shows the chat's current model. Empty/invalid
  selection highlights the selector and disables the send button (in addition to the
  empty-text disable).
- **Selection logic:**
  - On opening a chat, fetch `GET /models` and read `chat.model`.
  - If `chat.model` is `null` or not in the list (removed from Ollama) → "choose a model"
    state, send blocked.
  - Changing the model → `PATCH /chats/{id}` `{model}`, update the chat locally.
  - New chat (not yet created): keep the choice in state / `localStorage` (last used);
    pass `model` to `POST /chats`. If last-used isn't in the current list, prompt to pick.
- **API layer (`chatApi.ts`):** `listModels()`, `patchChatModel(id, model)`,
  `createChat(title, model?)`. `types.ts`: `ChatOut.model`, `ModelsOut`.
- **Errors:** a `409` from send/patch is surfaced in the UI ("model unavailable, pick
  another") — normally unreachable since send is pre-blocked.

## Testing (TDD)

- Backend: `list_models` (mock httpx), `begin_turn` raises `ModelUnavailableError`
  (fake agent), `PATCH` validation, `GET /models` shape + Ollama-down 502.
- Frontend: msw mock for `/models`, selector renders, send blocked without a valid model,
  `PATCH` fires on change.
