# Frontend slice: chat rendering on assistant-ui (design)

Date: 2026-07-04
Branch: `feature/frontend-chat-rendering`
Status: design approved, pending spec review

## 1. Purpose & scope

The chat data layer works (auth, chat list, per-chat model, SSE streaming) but the
**thread rendering is broken/limited**: assistant replies are shown as raw plain text
(`{message.content}`), so any markdown from the model — **tables, code, lists** — renders
unformatted, and the user reports "messages are not displayed". This slice fixes rendering
and re-platforms the thread view onto **assistant-ui** with a **parts-based, extensible**
message model, so future subsystems (tool calls, artifacts, citations, attachments) slot in
without a rewrite.

**In scope:**
- **Diagnose & fix** the "messages not displayed" bug — reproduced against the real backend
  + Ollama, root-caused by *layer* (data vs view) before any migration (see §6).
- **Re-platform the active thread** onto assistant-ui headless primitives, styled with our
  existing CSS Modules + `tokens.css` (liquid-glass look preserved 1:1).
- **Markdown rendering**: full **GFM** (tables, strikethrough, task lists, autolinks),
  **code blocks** with design-palette syntax highlighting + a "Copy" button, and **HTML
  sanitization** of model output.
- **Composer** re-platformed onto `ComposerPrimitive`, keeping our design (model pill,
  future tools pill) as custom children (decision B, §5.4).
- **Behaviors**: auto-scroll to newest, history loading + error/retry states, copy-message
  and regenerate actions.

**Deferred (extension points left clean; no backend data yet):**
- Real tool-call blocks, artifact cards/panel, citations/sources, attachments — the
  message-part model reserves their types but no renderers are built this slice.
- KaTeX/math, message editing/branching UI, Settings/MCP/Memory screens.

**Explicitly out of scope:** any backend change; the default styled assistant-ui package
(Tailwind) — we use **only** headless primitives; real LLM calls in tests.

The UI stays pixel-faithful to `design/design_handoff_capybaraagent/README.md`; on conflict
the README tokens win.

## 2. Backend surface consumed (unchanged)

No new endpoints. Same as the existing frontend slice:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/chats/{id}` | Chat + full message history (`ChatDetailOut`) |
| `POST` | `/chats/{id}/messages` | `{content}` → **SSE** `delta` / `done` / `error` |
| `PATCH` | `/chats/{id}` | Set chat model |

SSE event shapes (from `chats.py`), unchanged:
- `event: delta`  `data: {"text": "..."}`
- `event: done`   `data: {"message_id": "...", "usage": {...}}`
- `event: error`  `data: {"message": "..."}`

If diagnosis (§6) finds the bug is server-side (e.g. SSE buffering, missing flush headers),
that fix is a **separate, minimal** change gated by the diagnosis and called out explicitly —
not folded silently into the frontend work.

## 3. Library choice: assistant-ui (ExternalStoreRuntime)

Chosen deliberately for the **long-term** roadmap (tool UI, generative UI, attachments,
editing, branching) — assistant-ui's native message model is already **parts-based**, which
is exactly the "extensible now, fill in later" shape we want.

- **Runtime: `ExternalStoreRuntime`.** *We* own the message array (backend history + live
  SSE stream) and expose it via `useExternalStoreRuntime`. assistant-ui renders it and turns
  features on by which callbacks we provide. This keeps our data/persistence layer intact —
  assistant-ui is the **view + interaction** layer only, not a new data store.
- **Headless primitives only** (`@assistant-ui/react`): `ThreadPrimitive`,
  `MessagePrimitive`, `ComposerPrimitive`, `ThreadPrimitive.Viewport` (auto-scroll),
  `ThreadPrimitive.ScrollToBottom`. Styled with our CSS Modules — no Tailwind, no default
  theme; liquid-glass design is unaffected.
- **Markdown** via `@assistant-ui/react-markdown` (`MarkdownTextPrimitive`) with
  `remarkPlugins=[remarkGfm]` and a `rehype-sanitize` schema; code blocks rendered by a
  custom component (§5.3).

**New dependencies:** `@assistant-ui/react`, `@assistant-ui/react-markdown`, `remark-gfm`,
`rehype-sanitize`, `react-syntax-highlighter` (+ `@types/react-syntax-highlighter`).

## 4. Architecture (extends the existing frontend, same boundaries)

```
frontend/src/
  api/            # unchanged: client.ts, sse.ts, types.ts
  chat/
    useChats.ts        # unchanged
    useChatStream.ts   # our store: history + live streaming (source of runtime state)
    useModels.ts       # unchanged
    runtime.ts         # NEW: builds ExternalStoreRuntime from our store
    convertMessage.ts  # NEW: our ChatMessage -> assistant-ui ThreadMessage (parts)
    parts.ts           # NEW: MessagePart union (text now; tool-call/artifact/... reserved)
  components/
    Thread.tsx         # NEW: ThreadPrimitive.Viewport + message list + ScrollToBottom
    MessageMarkdown.tsx# NEW: MarkdownTextPrimitive (gfm + sanitize) + code renderer
    CodeBlock.tsx      # NEW: syntax-highlighted <pre> + Copy button (design palette)
    Composer.tsx       # REWORK: ComposerPrimitive.Root/Input/Send/Cancel + model pill child
    Message.tsx        # REWORK/retire: user bubble + assistant row via MessagePrimitive
    ...                # Sidebar, CapyLogo, BackgroundGlow unchanged
  screens/
    ChatScreen.tsx     # REWORK: wrap active thread in <AssistantRuntimeProvider>
```

Boundaries hold: `useChatStream` owns data/effects; `runtime.ts`/`convertMessage.ts`
translate our shape ↔ assistant-ui's; components stay presentational. Files stay small and
independently testable.

## 5. Design details

### 5.1 Extensible message-part model
`parts.ts` defines a discriminated union. This slice implements only `text`; the other
variants are declared (or reserved via comments) so `convertMessage.ts` and the renderer
gain new branches later without touching the thread:

```ts
type MessagePart =
  | { type: 'text'; text: string }
  // reserved (future slices, no backend yet):
  // | { type: 'tool-call'; name: string; args: unknown; result?: unknown; status }
  // | { type: 'artifact'; id: string; title: string; ... }
  // | { type: 'source'; id: string; url: string; title: string }
```

Our backend gives text-only messages today, so `convertMessage` wraps `content` into a
single `text` part. assistant-ui renders parts through pluggable components — adding a
`tool-call` renderer later is additive.

### 5.2 Runtime wiring
`runtime.ts` calls `useExternalStoreRuntime({ messages, isRunning, onNew, onReload,
convertMessage })`:
- `messages` — history + streaming message from `useChatStream`.
- `isRunning` — the store's `sending`/streaming flag (single source of truth; §5.4).
- `onNew(message)` — sends via the existing store path (POST + SSE).
- `onReload(parentId?)` — regenerate: re-run the last user turn.

`ChatScreen` wraps the active view in `<AssistantRuntimeProvider runtime={...}>`.

### 5.3 Markdown & code
- `MessageMarkdown.tsx` uses `MarkdownTextPrimitive` with `remarkPlugins=[remarkGfm]` and a
  `rehype-sanitize` schema allowing the safe markdown subset (drop `<script>`, event
  handlers, `javascript:` URLs). Element styles (`table`, `th/td`, `blockquote`, `a`,
  `ul/ol`, `strong`) come from a CSS Module matching the handoff.
- `CodeBlock.tsx` wraps `react-syntax-highlighter` (Prism) with a **custom theme object
  built from the design's code palette** (keyword `#c58fd6`, function/type `#8fbcdb`,
  string `#8fbf9e`, comment `#7a7268`, plain `#d6cdc3`, bg `rgba(0,0,0,.28)`, JetBrains
  Mono 12.5px/1.7). Header row: accent dot + language label + **Copy** button
  (clipboard write + transient "Copied" state). Prism over Shiki: lighter and maps exactly
  onto the fixed palette.

### 5.4 Composer (decision B)
`Composer.tsx` is rebuilt on `ComposerPrimitive`:
- `ComposerPrimitive.Root` (form) → `ComposerPrimitive.Input` (textarea, auto-grow) +
  action row: paperclip (visual, disabled), **model pill** (our existing per-chat model
  selector, unchanged behaviour) as a **custom child**, spacer,
  `ComposerPrimitive.Send`/`Cancel` styled as the accent send/stop button.
- Runtime is the single source of truth for "running"/draft — removing the current
  `sending` vs `isRunning` split. Send is gated while running; Cancel aborts the stream.
- Per-chat model selection and `loadLastModel`/`saveLastModel` logic are preserved; the pill
  simply lives inside the primitive.

### 5.5 Behaviors
- **Auto-scroll** — `ThreadPrimitive.Viewport` sticks to bottom while streaming; a
  `ScrollToBottom` affordance appears when scrolled up.
- **History loading** — a lightweight skeleton/spinner in the thread while `getChat` is in
  flight; empty history renders nothing (composer still usable).
- **Errors** — stream `error` event or network failure → an in-thread error row + retry
  (via `onReload`); never a silently broken bubble.
- **Actions** — `MessagePrimitive.Action` for copy-message and regenerate under assistant
  replies; per-block Copy on code (§5.3). Reduced-motion respected for the caret.

## 6. Diagnosis-first workstream (before migration)

The "not displayed" bug is fixed **first and independently**, because assistant-ui cannot
fix a data-layer fault. Using systematic-debugging:
1. **Reproduce** with the real backend + Ollama running (`docker compose up`, dev server,
   send a message).
2. **Localize the layer:**
   - *Data* — SSE not arriving/parsing: proxy buffering of `text/event-stream`, missing
     `X-Accel-Buffering: no`/flush, history payload shape, auth token on the stream request.
   - *View* — CSS (text color vs background, zero-height thread), state wiring, effect deps.
3. **Fix at the root.** If data-layer, patch the correct place (frontend store or, if
   server-side, a minimal backend change called out explicitly per §2). If view-layer, it is
   subsumed by the assistant-ui migration — verified by a regression test.

Rationale: re-platforming on top of an undiagnosed data bug would ship a still-broken chat.

## 7. Error handling & edge cases

- Stream network failure / `error` event → in-thread error row + retry; no broken bubble.
- `401` mid-stream → existing auto-logout path (unchanged).
- Markdown with malicious HTML → stripped by `rehype-sanitize` (covered by a test).
- Very long code blocks → horizontal scroll within the block, thread width unchanged.
- Reduced motion → caret/scroll animations respect `prefers-reduced-motion`.

## 8. Testing (TDD — tests first)

Vitest + RTL + MSW (already configured). No real backend or LLM.
- `convertMessage` — text message → single `text` part; shape stable for future parts.
- `MessageMarkdown` — renders a GFM **table**, a fenced **code block**, and **sanitizes**
  `<script>`/`javascript:` out of model output.
- `CodeBlock` — Copy writes to clipboard and shows the transient confirmation.
- Streaming — deltas append in order, `isRunning` flips off on `done`, `error` surfaces a
  retryable row (drives the runtime store).
- Thread — auto-scroll invoked on new content; copy/regenerate actions call the runtime.
- A **regression test** pinning the fixed "not displayed" behavior from §6.
- Existing tests adapted to the reworked Composer/Message/ChatScreen.

## 9. Deliverables

1. `chat/parts.ts`, `chat/convertMessage.ts`, `chat/runtime.ts` (+ tests).
2. `components/Thread.tsx`, `MessageMarkdown.tsx`, `CodeBlock.tsx` (+ tests).
3. Reworked `Composer.tsx` (ComposerPrimitive + custom children), `Message.tsx`,
   `ChatScreen.tsx` (runtime provider) with adapted tests.
4. New deps added to `frontend/package.json` (§3).
5. The diagnosis fix from §6 (frontend, or a minimal explicit backend change if server-side).
6. CSS Modules for markdown/code/thread matching the handoff palette & typography.

## 10. Success criteria

- Running backend + Ollama: send a message → reply **streams and renders**, with markdown
  **tables, lists, and highlighted code** formatted correctly; a code block copies on click.
- History renders on chat select and on reload; auto-scroll follows the newest message.
- Stream error shows a retryable in-thread row; Cancel stops an in-flight reply.
- Copy-message and regenerate work on assistant replies.
- Model output containing `<script>` is sanitized (no execution).
- `npm run lint`, `npm run test`, `tsc --noEmit`, `npm run build` all pass.
- UI still matches the handoff tokens; only headless assistant-ui is used (no Tailwind theme).
- Extension points (`MessagePart` union, `convertMessage`) documented for tool-call/artifact
  slices; none of that UI is built here (YAGNI).
