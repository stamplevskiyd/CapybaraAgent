# Filter non-chat models from the available-models list

**Date:** 2026-07-06
**Status:** Approved, ready for implementation
**Scope:** Backend (Slice 1 chat core) — `OllamaAgent`

## Problem

`OllamaAgent.list_models()` returns every model installed in Ollama, taken from
`/api/tags`. That includes embedding-only models such as `nomic-embed-text`, which
cannot serve chat. Because the same list feeds the `/models` endpoint (what the UI
offers for selection) *and* `ensure_available()` (the pre-send guard), a user can pick
an embedding model and the turn fails deep in the provider:

```
pydantic_ai.exceptions.ModelHTTPError: status_code: 400,
model_name: nomic-embed-text:latest,
body: {'message': '"nomic-embed-text:latest" does not support chat', ...}
```

The fix must be **generic** — exclude any model that cannot chat, not `nomic-embed-text`
specifically.

## Approach

Filter inside `OllamaAgent.list_models()`, the single place that produces the list.
Fixing it there covers both consumers (`/models` endpoint and `ensure_available()`).

Detection uses Ollama's authoritative capability signal: `POST /api/show`
`{"model": <name>}` returns a `capabilities` array. Embedding models report
`["embedding"]`; chat models include `"completion"`.

### Algorithm

1. `GET /api/tags` → list of model names (as today).
2. For each name, `POST /api/show` `{"model": name}` **concurrently**
   (`asyncio.gather`) over a single shared `httpx.AsyncClient`. Read `capabilities`.
3. Include a model **unless** its `capabilities` is present and does **not** contain
   `"completion"`. That is: drop only on a *positive* "cannot chat" signal.

### Fail-open rule (deliberate)

If a model's `/api/show` response has **no** `capabilities` field (e.g. an older Ollama
that does not report it), keep the model. We drop a model only when we positively know
it lacks `"completion"`. This preserves today's behaviour for providers that don't
report capabilities rather than silently hiding every model.

Result: `nomic-embed-text` (`["embedding"]`) is dropped; `llama3.1`
(`["completion", ...]`) is kept; a capability-less response is kept.

### Error handling

- `/api/tags` unreachable, error status, or unexpected shape → `ModelProviderError`
  (unchanged).
- A **transport-level** failure on any `/api/show` call means the server went away →
  `ModelProviderError`. A per-model non-200 status or a body without `capabilities` is
  **not** an outage — it falls under the fail-open rule (model kept), because a single
  model's `show` quirk must not blank the whole list.

No new error type; the router's existing `502` mapping for `ModelProviderError` is
unchanged.

## Affected code

- `src/capybara/agent/ollama.py` — `list_models()` gains the per-model capability
  filter. Open one `httpx.AsyncClient` for the tags call and all show calls.
- No change to `base.py` (`ensure_available` still calls `list_models`), the `/models`
  router, or schemas.

## Out of scope

- **Caching.** Chosen explicitly: no cache. `ensure_available()` runs `list_models()`
  per send, so each send makes N `/api/show` calls. Acceptable for a local Ollama with a
  handful of models.
- The pre-existing `base.py:154` `except ValueError, TypeError:` syntax bug — unrelated,
  left alone.
- Embeddings are unaffected: `embed()` targets `settings.embedding_model` directly and
  does not go through `list_models()`.

## Testing

Existing mock handlers in `tests/test_agent_models.py` answer only `/api/tags`; they
must also answer `/api/show`. A small shared handler helper that dispatches on
`request.url.path` keeps the tests readable.

New / updated cases:

1. **Embedding model excluded** — `/api/tags` returns a chat model and
   `nomic-embed-text`; `/api/show` reports `["completion"]` and `["embedding"]`
   respectively; `list_models()` returns only the chat model.
2. **Completion model kept** — a model reporting `["completion", "tools"]` is included.
3. **Missing capabilities kept (fail-open)** — a `/api/show` body without
   `capabilities` is included.
4. **Provider outage** — a transport error on `/api/show` raises `ModelProviderError`.
5. Existing `list_models` / `ensure_available` tests updated so their mock transport
   also serves `/api/show` for the returned names.

All existing quality gates apply: `ruff check`, `ruff format`, `mypy src` (strict),
`pytest`. Docstrings required on any new helper.
