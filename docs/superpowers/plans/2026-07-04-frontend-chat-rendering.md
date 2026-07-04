# Frontend Chat Rendering (assistant-ui) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the "messages not displayed" bug and re-platform the active chat thread onto assistant-ui with a parts-based extensible message model, GFM markdown + sanitized HTML, Prism code highlighting with copy, and a ComposerPrimitive-based composer keeping our model pill.

**Architecture:** Keep our data layer (`useChatStream`, `useChats`, SSE) as the source of truth and expose it to assistant-ui via `ExternalStoreRuntime`. assistant-ui headless primitives render the thread and composer; all styling stays in CSS Modules + `tokens.css` (no Tailwind, no default theme). A `MessagePart` union + `convertMessage` translate our messages into assistant-ui's parts-based `ThreadMessageLike`, leaving clean extension points for future tool-call/artifact/citation parts.

**Tech Stack:** React 18 + TypeScript + Vite, CSS Modules, `@assistant-ui/react`, `@assistant-ui/react-markdown`, `remark-gfm`, `rehype-sanitize`, `react-syntax-highlighter` (Prism), Vitest + RTL + MSW.

## Global Constraints

- **Package manager:** `npm` inside `frontend/` (has its own `package.json`; Node ≥ 20).
- **No backend change** unless Task 1 diagnosis proves the bug is server-side; any such change is minimal and called out explicitly in that task.
- **Headless assistant-ui only** — import from `@assistant-ui/react` / `@assistant-ui/react-markdown`; do **not** install or use `@assistant-ui/react-ui` (Tailwind default theme).
- **Styling:** CSS Modules + `src/theme/tokens.css`; match `design/design_handoff_capybaraagent/README.md`. On conflict, README tokens win.
- **Code palette (verbatim):** keyword `#c58fd6`, function/type `#8fbcdb`, JSX tag `#e0967a`, attribute `#cbb48c`, string `#8fbf9e`, plain `#d6cdc3`, comment/muted `#7a7268`; code bg `rgba(0,0,0,.28)`; font JetBrains Mono 12.5px / line-height 1.7.
- **Quality gates (all must pass at the end):** `npm run lint`, `npm run test`, `npm run typecheck` (`tsc --noEmit`), `npm run build`.
- **TDD:** write the failing test first for every deterministic unit. Commit after each green step. Every module/exported function gets a doc comment (matches existing frontend style).
- **Scoped git staging:** stage only the files a task touches (`git add <paths>`), never `git add -A` — the user commits concurrently.

---

### Task 1: Diagnose & fix "messages not displayed"

Independent, done **first**. This is the one investigation-shaped task; use **superpowers:systematic-debugging**. assistant-ui will not fix a data-layer fault, so the root cause must be found before migration.

**Files:**
- Investigate: `frontend/src/chat/useChatStream.ts`, `frontend/src/api/sse.ts`, `frontend/src/api/client.ts`, `frontend/src/screens/ChatScreen.tsx`, `frontend/vite.config.ts`, `src/capybara/api/routers/chats.py`
- Likely fix: one of the above (frontend) or a minimal `chats.py` header change (backend, only if server-side)
- Test: `frontend/src/chat/useChatStream.test.tsx` or a new focused regression test

- [ ] **Step 1: Reproduce against the real stack.** Start Postgres + API (`docker compose up`), ensure Ollama is running on the host with at least one model, run `cd frontend && npm install && npm run dev`. Log in, create a chat, pick a model, send a message. Record the exact symptom: does the user bubble appear? does any assistant text appear? does the network tab show the SSE response streaming or arriving all-at-once/empty? Check the browser console for errors.

- [ ] **Step 2: Localize the layer using the evidence.** Decide data vs view:
  - **Data suspects:** (a) SSE buffered by the Vite proxy — the response arrives only on close, or not at all; look for missing streaming. (b) `POST /chats/{id}/messages` returns non-200 (model unavailable → 409/502) so the stream never starts. (c) `getChat` history payload shape mismatch. (d) auth token missing on the stream request.
  - **View suspects:** (e) content renders but is invisible/clipped by layout; (f) state wiring (`messages` never updated, effect deps).
  Confirm with a direct check: `curl -N -H "Authorization: Bearer <token>" -X POST http://localhost:8000/chats/<id>/messages -H 'Content-Type: application/json' -d '{"content":"hi"}'` — if curl streams `event: delta` lines but the browser does not, the fault is the proxy/browser layer; if curl also fails, it is backend/model.

- [ ] **Step 3: If server-side SSE buffering — add flush-friendly headers (minimal backend change).** In `src/capybara/api/routers/chats.py`, add headers to the `StreamingResponse` so proxies do not buffer:

```python
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
```

- [ ] **Step 4: Write a regression test capturing the fixed behavior.** If the fault was frontend, add a Vitest+MSW test to `frontend/src/chat/useChatStream.test.tsx` that fails before the fix and passes after (e.g. asserting deltas from a chunked SSE stream land in `messages`). If backend, add/extend a pytest in `tests/` asserting the response carries `X-Accel-Buffering: no`. Write the test to fail first, then apply the fix.

- [ ] **Step 5: Run the targeted test to confirm it passes.**

Run (frontend): `cd frontend && npx vitest run src/chat/useChatStream.test.tsx`
Run (backend, if applicable): `uv run pytest tests -k chat_stream -q`
Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
# frontend fix example — adjust paths to what actually changed
git add frontend/src/chat/useChatStream.test.tsx frontend/src/<fixed-file>
git commit -m "fix(frontend): render streamed chat messages

Root cause: <one line from the investigation>."
```

---

### Task 2: Add dependencies & pin the assistant-ui reference

**Files:**
- Modify: `frontend/package.json`

**Interfaces:**
- Produces: the packages every later task imports (`@assistant-ui/react`, `@assistant-ui/react-markdown`, `remark-gfm`, `rehype-sanitize`, `react-syntax-highlighter`).

- [ ] **Step 1: Install runtime deps.**

Run:
```bash
cd frontend && npm install @assistant-ui/react @assistant-ui/react-markdown remark-gfm rehype-sanitize react-syntax-highlighter
```

- [ ] **Step 2: Install types.**

Run:
```bash
cd frontend && npm install -D @types/react-syntax-highlighter
```

- [ ] **Step 3: Capture the generated reference component for exact prop names.** assistant-ui prop/import names are version-sensitive. Generate the canonical `thread.tsx` to read (do **not** keep it in the app — it pulls Tailwind classes we won't use):

Run:
```bash
cd frontend && npx assistant-ui@latest add thread --help 2>/dev/null || true
```
Then open the assistant-ui docs "Thread" and "Composer" primitive pages in a browser, or inspect `node_modules/@assistant-ui/react` type declarations, to confirm the exact primitive component names used in Tasks 7–9 (`ThreadPrimitive.Root/Viewport/Messages/Empty/ScrollToBottom`, `MessagePrimitive.Root/Content`, `ActionBarPrimitive.Root/Copy/Reload`, `ComposerPrimitive.Root/Input/Send/Cancel`). Note any deviation and adjust those tasks' JSX accordingly.

- [ ] **Step 4: Verify the project still builds & type-checks with the new deps.**

Run: `cd frontend && npm run typecheck && npm run build`
Expected: PASS (no code changes yet).

- [ ] **Step 5: Commit.**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "build(frontend): add assistant-ui, markdown, sanitize, prism deps"
```

---

### Task 3: Message-part model + convertMessage

**Files:**
- Create: `frontend/src/chat/parts.ts`
- Create: `frontend/src/chat/convertMessage.ts`
- Test: `frontend/src/chat/convertMessage.test.ts`

**Interfaces:**
- Consumes: `ChatMessage` from `frontend/src/chat/useChatStream.ts` (`{ id, role, content, streaming, error? }`).
- Produces:
  - `parts.ts`: `type MessagePart = { type: 'text'; text: string }` (union, extensible).
  - `convertMessage.ts`: `convertMessage(m: ChatMessage): ThreadMessageLike` (from `@assistant-ui/react`).

- [ ] **Step 1: Write the failing test.**

```ts
// frontend/src/chat/convertMessage.test.ts
import { convertMessage } from './convertMessage'
import type { ChatMessage } from './useChatStream'

test('wraps text content into a single text part', () => {
  const msg: ChatMessage = { id: 'm1', role: 'assistant', content: 'Привет', streaming: false }
  const out = convertMessage(msg)
  expect(out.role).toBe('assistant')
  expect(out.id).toBe('m1')
  expect(out.content).toEqual([{ type: 'text', text: 'Привет' }])
})

test('marks a streaming message as running, settled otherwise', () => {
  const streaming: ChatMessage = { id: 'm2', role: 'assistant', content: 'partial', streaming: true }
  const done: ChatMessage = { id: 'm3', role: 'assistant', content: 'full', streaming: false }
  expect(convertMessage(streaming).status?.type).toBe('running')
  expect(convertMessage(done).status).toBeUndefined()
})
```

- [ ] **Step 2: Run it to verify it fails.**

Run: `cd frontend && npx vitest run src/chat/convertMessage.test.ts`
Expected: FAIL ("Cannot find module './convertMessage'").

- [ ] **Step 3: Implement `parts.ts`.**

```ts
// frontend/src/chat/parts.ts
/** Renderable parts of a chat message. Text only today; tool-call/artifact/source reserved. */
export type MessagePart =
  | { type: 'text'; text: string }
// Future slices (no backend data yet) will add e.g.:
// | { type: 'tool-call'; toolName: string; args: unknown; result?: unknown; status: 'running' | 'complete' | 'error' }
// | { type: 'artifact'; id: string; title: string }
// | { type: 'source'; id: string; url: string; title: string }
```

- [ ] **Step 4: Implement `convertMessage.ts`.**

```ts
// frontend/src/chat/convertMessage.ts
/** Translate our ChatMessage into assistant-ui's parts-based ThreadMessageLike. */
import type { ThreadMessageLike } from '@assistant-ui/react'
import type { ChatMessage } from './useChatStream'

export function convertMessage(m: ChatMessage): ThreadMessageLike {
  return {
    id: m.id,
    role: m.role,
    content: [{ type: 'text', text: m.content }],
    status: m.streaming ? { type: 'running' } : undefined,
  }
}
```

- [ ] **Step 5: Run the test to verify it passes.**

Run: `cd frontend && npx vitest run src/chat/convertMessage.test.ts`
Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add frontend/src/chat/parts.ts frontend/src/chat/convertMessage.ts frontend/src/chat/convertMessage.test.ts
git commit -m "feat(frontend): parts-based message model + convertMessage adapter"
```

---

### Task 4: CodeBlock (Prism highlighting + copy)

**Files:**
- Create: `frontend/src/components/CodeBlock.tsx`
- Create: `frontend/src/components/CodeBlock.module.css`
- Create: `frontend/src/components/prismTheme.ts`
- Test: `frontend/src/components/CodeBlock.test.tsx`

**Interfaces:**
- Produces: `CodeBlock({ code, language }: { code: string; language?: string })` — a highlighted `<pre>` with a header (language label + Copy button). Used by Task 5's markdown code renderer.

- [ ] **Step 1: Write the failing test.**

```tsx
// frontend/src/components/CodeBlock.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CodeBlock } from './CodeBlock'

test('renders code and copies it to the clipboard', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.assign(navigator, { clipboard: { writeText } })
  render(<CodeBlock code="print('hi')" language="python" />)
  expect(screen.getByText("print('hi')")).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /копировать/i }))
  expect(writeText).toHaveBeenCalledWith("print('hi')")
})
```

- [ ] **Step 2: Run it to verify it fails.**

Run: `cd frontend && npx vitest run src/components/CodeBlock.test.tsx`
Expected: FAIL ("Cannot find module './CodeBlock'").

- [ ] **Step 3: Implement the design-palette Prism theme.**

```ts
// frontend/src/components/prismTheme.ts
/** react-syntax-highlighter (Prism) style built from the design handoff code palette. */
import type { CSSProperties } from 'react'

const mono = "'JetBrains Mono', monospace"

export const prismTheme: Record<string, CSSProperties> = {
  'code[class*="language-"]': { color: '#d6cdc3', fontFamily: mono, fontSize: '12.5px', lineHeight: 1.7, background: 'none' },
  'pre[class*="language-"]': { color: '#d6cdc3', fontFamily: mono, fontSize: '12.5px', lineHeight: 1.7, background: 'none', margin: 0, padding: 0, overflow: 'auto' },
  comment: { color: '#7a7268' },
  prolog: { color: '#7a7268' },
  doctype: { color: '#7a7268' },
  cdata: { color: '#7a7268' },
  punctuation: { color: '#d6cdc3' },
  keyword: { color: '#c58fd6' },
  'attr-name': { color: '#cbb48c' },
  tag: { color: '#e0967a' },
  string: { color: '#8fbf9e' },
  char: { color: '#8fbf9e' },
  function: { color: '#8fbcdb' },
  'class-name': { color: '#8fbcdb' },
  builtin: { color: '#8fbcdb' },
  number: { color: '#8fbf9e' },
  operator: { color: '#d6cdc3' },
}
```

- [ ] **Step 4: Implement `CodeBlock.module.css`.**

```css
/* frontend/src/components/CodeBlock.module.css */
.block { border: 1px solid rgba(255, 255, 255, 0.09); border-radius: 13px; overflow: hidden; margin: 10px 0; }
.header { display: flex; align-items: center; gap: 8px; padding: 7px 12px; background: rgba(255, 255, 255, 0.03); border-bottom: 1px solid rgba(255, 255, 255, 0.06); }
.dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent, #d89b6c); }
.lang { font-family: 'JetBrains Mono', monospace; font-size: 11.5px; color: #a29a90; }
.copy { margin-left: auto; background: none; border: none; color: #a29a90; font-size: 12px; cursor: pointer; padding: 2px 6px; border-radius: 6px; }
.copy:hover { background: rgba(255, 255, 255, 0.06); color: #d6cdc3; }
.body { padding: 12px 14px; background: rgba(0, 0, 0, 0.28); overflow-x: auto; }
```

- [ ] **Step 5: Implement `CodeBlock.tsx`.**

```tsx
// frontend/src/components/CodeBlock.tsx
/** Syntax-highlighted code block with a language label and a copy-to-clipboard button. */
import { useState } from 'react'
import { PrismLight as SyntaxHighlighter } from 'react-syntax-highlighter'
import { prismTheme } from './prismTheme'
import styles from './CodeBlock.module.css'

export function CodeBlock({ code, language }: { code: string; language?: string }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    await navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <div className={styles.block}>
      <div className={styles.header}>
        <span className={styles.dot} aria-hidden="true" />
        <span className={styles.lang}>{language ?? 'text'}</span>
        <button type="button" className={styles.copy} onClick={copy}>
          {copied ? 'Скопировано' : 'Копировать'}
        </button>
      </div>
      <div className={styles.body}>
        <SyntaxHighlighter language={language} style={prismTheme} customStyle={{ background: 'none', margin: 0, padding: 0 }}>
          {code}
        </SyntaxHighlighter>
      </div>
    </div>
  )
}
```

- [ ] **Step 6: Run the test to verify it passes.**

Run: `cd frontend && npx vitest run src/components/CodeBlock.test.tsx`
Expected: PASS.

- [ ] **Step 7: Commit.**

```bash
git add frontend/src/components/CodeBlock.tsx frontend/src/components/CodeBlock.module.css frontend/src/components/prismTheme.ts frontend/src/components/CodeBlock.test.tsx
git commit -m "feat(frontend): code block with Prism highlighting and copy button"
```

---

### Task 5: MessageMarkdown (GFM + sanitize + code renderer)

**Files:**
- Create: `frontend/src/components/MessageMarkdown.tsx`
- Create: `frontend/src/components/MessageMarkdown.module.css`
- Test: `frontend/src/components/MessageMarkdown.test.tsx`

**Interfaces:**
- Consumes: `CodeBlock` (Task 4), `@assistant-ui/react-markdown`, `remark-gfm`, `rehype-sanitize`.
- Produces: `MarkdownText` — a component usable as `MessagePrimitive.Content` text renderer (`components={{ Text: MarkdownText }}`) in Task 7.

- [ ] **Step 1: Write the failing test.** Render the primitive directly with a message via the runtime is heavy; instead test the underlying renderer through a thin harness that assistant-ui exposes. Keep it behavioral: a table renders as a table, a fenced block renders code, `<script>` is stripped.

```tsx
// frontend/src/components/MessageMarkdown.test.tsx
import { render, screen } from '@testing-library/react'
import { MarkdownText } from './MessageMarkdown'
import { TestMarkdownHarness } from './MessageMarkdown'  // see Step 3

test('renders a GFM table', () => {
  render(<TestMarkdownHarness text={'| a | b |\n|---|---|\n| 1 | 2 |'} />)
  expect(screen.getByRole('table')).toBeInTheDocument()
  expect(screen.getByText('a')).toBeInTheDocument()
})

test('renders fenced code via CodeBlock', () => {
  render(<TestMarkdownHarness text={'```python\nprint(1)\n```'} />)
  expect(screen.getByRole('button', { name: /копировать/i })).toBeInTheDocument()
})

test('sanitizes raw HTML script out of model output', () => {
  render(<TestMarkdownHarness text={'hello <script>window.__x=1</script> world'} />)
  expect(document.querySelector('script')).toBeNull()
})
```

- [ ] **Step 2: Run it to verify it fails.**

Run: `cd frontend && npx vitest run src/components/MessageMarkdown.test.tsx`
Expected: FAIL ("Cannot find module './MessageMarkdown'").

- [ ] **Step 3: Implement `MessageMarkdown.tsx`.** `MarkdownTextPrimitive` accepts `remarkPlugins`, `rehypePlugins`, `className`, and a `components` map. The `code` component receives the fenced language + children; route fenced blocks to `CodeBlock`. Export a `TestMarkdownHarness` that renders the same `MarkdownTextPrimitive` with static `children` text so it can be unit-tested without a runtime.

```tsx
// frontend/src/components/MessageMarkdown.tsx
/** Markdown renderer for assistant messages: GFM + sanitized HTML + design-styled code. */
import { MarkdownTextPrimitive } from '@assistant-ui/react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeSanitize from 'rehype-sanitize'
import { CodeBlock } from './CodeBlock'
import styles from './MessageMarkdown.module.css'

const components = {
  code({ className, children }: { className?: string; children?: React.ReactNode }) {
    const lang = /language-(\w+)/.exec(className ?? '')?.[1]
    const text = String(children ?? '')
    // Fenced blocks carry a language class or a trailing newline; inline code does not.
    if (lang || text.includes('\n')) {
      return <CodeBlock code={text.replace(/\n$/, '')} language={lang} />
    }
    return <code className={styles.inlineCode}>{children}</code>
  },
}

/** Text-part renderer plugged into MessagePrimitive.Content in the Thread. */
export function MarkdownText() {
  return (
    <MarkdownTextPrimitive
      className={styles.markdown}
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeSanitize]}
      components={components}
    />
  )
}

/** Test-only: render markdown from a static string without a runtime. */
export function TestMarkdownHarness({ text }: { text: string }) {
  return (
    <MarkdownTextPrimitive
      className={styles.markdown}
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeSanitize]}
      components={components}
    >
      {text}
    </MarkdownTextPrimitive>
  )
}
```

Note: if the installed `@assistant-ui/react-markdown` does not accept static `children` on `MarkdownTextPrimitive`, replace `TestMarkdownHarness` with a direct `react-markdown` render using the same `remarkPlugins`/`rehypePlugins`/`components` (the sanitize/gfm behavior is what the test pins). Confirm against the version pulled in Task 2.

- [ ] **Step 4: Implement `MessageMarkdown.module.css`** (styles for markdown elements per handoff).

```css
/* frontend/src/components/MessageMarkdown.module.css */
.markdown { font-size: 14.5px; line-height: 1.62; color: #e8dfd5; }
.markdown p { margin: 0 0 10px; }
.markdown strong { color: #f2ece4; font-weight: 600; }
.markdown a { color: var(--accent, #d89b6c); text-decoration: underline; }
.markdown ul, .markdown ol { margin: 8px 0; padding-left: 22px; }
.markdown li { margin: 3px 0; }
.markdown blockquote { border-left: 2px solid rgba(216, 155, 108, 0.4); margin: 10px 0; padding-left: 12px; color: #c9c0b6; }
.inlineCode { font-family: 'JetBrains Mono', monospace; font-size: 12.5px; background: rgba(255, 255, 255, 0.06); padding: 1px 5px; border-radius: 5px; }
.markdown table { border-collapse: collapse; margin: 10px 0; width: 100%; font-size: 13.5px; }
.markdown th, .markdown td { border: 1px solid rgba(255, 255, 255, 0.1); padding: 6px 10px; text-align: left; }
.markdown th { background: rgba(255, 255, 255, 0.04); color: #f2ece4; font-weight: 600; }
```

- [ ] **Step 5: Run the test to verify it passes.**

Run: `cd frontend && npx vitest run src/components/MessageMarkdown.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add frontend/src/components/MessageMarkdown.tsx frontend/src/components/MessageMarkdown.module.css frontend/src/components/MessageMarkdown.test.tsx
git commit -m "feat(frontend): GFM markdown renderer with sanitize and code blocks"
```

---

### Task 6: Extend the store — isRunning, cancel, regenerate, chatId-safe send

**Files:**
- Modify: `frontend/src/chat/useChatStream.ts`
- Test: `frontend/src/chat/useChatStream.test.tsx`

**Interfaces:**
- Consumes: existing `useChatStream(chatId)` returning `{ messages, sending, send, loadHistory }`.
- Produces: `useChatStream(chatId)` returning `{ messages, sending, loadingHistory, send, loadHistory, cancel, regenerate }` where:
  - `send(text: string, chatIdOverride?: string): Promise<void>` — uses `chatIdOverride ?? chatId`.
  - `loadingHistory: boolean` — true while `getChat` is in flight (drives the thread loading state, spec §5.5).
  - `cancel(): void` — aborts an in-flight stream; the assistant message settles (`streaming:false`).
  - `regenerate(): Promise<void>` — re-sends the text of the last user message, dropping the last assistant message first.

- [ ] **Step 1: Write the failing tests** (add to the existing file).

```tsx
// append to frontend/src/chat/useChatStream.test.tsx
test('cancel stops an in-flight stream and settles the message', async () => {
  server.use(
    http.post('/api/chats/c1/messages', () => {
      const stream = new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode('event: delta\ndata: {"text":"partial"}\n\n'))
          // never closes; cancel() must abort it
        },
      })
      return new HttpResponse(stream, { headers: { 'Content-Type': 'text/event-stream' } })
    }),
  )
  const { result } = renderHook(() => useChatStream('c1'), { wrapper })
  act(() => { void result.current.send('Привет') })
  await waitFor(() => expect(result.current.messages.some((m) => m.content === 'partial')).toBe(true))
  act(() => { result.current.cancel() })
  await waitFor(() => expect(result.current.sending).toBe(false))
  const assistant = result.current.messages.find((m) => m.role === 'assistant')!
  expect(assistant.streaming).toBe(false)
})

test('regenerate re-sends the last user message', async () => {
  let calls = 0
  server.use(
    http.post('/api/chats/c1/messages', async ({ request }) => {
      calls++
      const { content } = (await request.json()) as { content: string }
      return new HttpResponse(
        `event: delta\ndata: {"text":"${content}!"}\n\nevent: done\ndata: {"message_id":"m${calls}"}\n\n`,
        { headers: { 'Content-Type': 'text/event-stream' } },
      )
    }),
  )
  const { result } = renderHook(() => useChatStream('c1'), { wrapper })
  await act(async () => { await result.current.send('Привет') })
  await act(async () => { await result.current.regenerate() })
  expect(calls).toBe(2)
  const assistants = result.current.messages.filter((m) => m.role === 'assistant')
  expect(assistants.at(-1)!.content).toBe('Привет!')
})
```

- [ ] **Step 2: Run to verify they fail.**

Run: `cd frontend && npx vitest run src/chat/useChatStream.test.tsx`
Expected: FAIL (`cancel` / `regenerate` not a function).

- [ ] **Step 3: Implement the store changes.** Add a `chatId` ref so `send` always uses the latest id; thread an `AbortController` through the fetch; add `cancel` and `regenerate`. Full new file:

```ts
// frontend/src/chat/useChatStream.ts
import { useCallback, useEffect, useRef, useState } from 'react'
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

/** Owns chat message state: history load + live SSE streaming, cancel, and regenerate. */
export function useChatStream(chatId: string | null) {
  const api = useApiClient()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [sending, setSending] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const chatIdRef = useRef(chatId)
  const abortRef = useRef<AbortController | null>(null)
  useEffect(() => {
    chatIdRef.current = chatId
  }, [chatId])

  const loadHistory = useCallback(async () => {
    if (!chatId) {
      setMessages([])
      return
    }
    setLoadingHistory(true)
    try {
      const detail = await getChat(api, chatId)
      setMessages(
        detail.messages.map((m) => ({
          id: m.id,
          role: m.role === 'user' ? 'user' : 'assistant',
          content: m.content,
          streaming: false,
        })),
      )
    } finally {
      setLoadingHistory(false)
    }
  }, [api, chatId])

  const send = useCallback(
    async (text: string, chatIdOverride?: string) => {
      const id = chatIdOverride ?? chatIdRef.current
      if (!id) return
      const assistantId = localId()
      setMessages((prev) => [
        ...prev,
        { id: localId(), role: 'user', content: text, streaming: false },
        { id: assistantId, role: 'assistant', content: '', streaming: true },
      ])
      const patch = (fn: (m: ChatMessage) => ChatMessage) =>
        setMessages((prev) => prev.map((m) => (m.id === assistantId ? fn(m) : m)))
      const controller = new AbortController()
      abortRef.current = controller
      setSending(true)
      try {
        const res = await api.stream(`/chats/${id}/messages`, { content: text }, controller.signal)
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
      } catch (err) {
        if (controller.signal.aborted) {
          patch((m) => ({ ...m, streaming: false }))
        } else {
          patch((m) => ({ ...m, streaming: false, error: true, content: 'Ошибка при получении ответа.' }))
        }
      } finally {
        setSending(false)
        abortRef.current = null
      }
    },
    [api],
  )

  const cancel = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  const regenerate = useCallback(async () => {
    let lastUser: ChatMessage | undefined
    setMessages((prev) => {
      lastUser = [...prev].reverse().find((m) => m.role === 'user')
      const lastAssistantIdx = prev.map((m) => m.role).lastIndexOf('assistant')
      return lastAssistantIdx === -1 ? prev : prev.filter((_, i) => i !== lastAssistantIdx)
    })
    if (lastUser) await send(lastUser.content)
  }, [send])

  return { messages, sending, loadingHistory, send, loadHistory, cancel, regenerate }
}
```

- [ ] **Step 4: Add the abort signal to the API client.** In `frontend/src/api/client.ts`, widen `stream` to accept an optional signal.

Modify the interface and impl:
```ts
// interface
stream(path: string, body: unknown, signal?: AbortSignal): Promise<Response>
// request() already forwards init; update the concrete stream():
stream: (path, body, signal) =>
  stream(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  }),
```

- [ ] **Step 5: Run the store tests to verify they pass.**

Run: `cd frontend && npx vitest run src/chat/useChatStream.test.tsx`
Expected: PASS (including the pre-existing streaming tests).

- [ ] **Step 6: Commit.**

```bash
git add frontend/src/chat/useChatStream.ts frontend/src/chat/useChatStream.test.tsx frontend/src/api/client.ts
git commit -m "feat(frontend): store cancel + regenerate + chatId-safe send"
```

---

### Task 7: Chat runtime (ExternalStoreRuntime wiring)

**Files:**
- Create: `frontend/src/chat/runtime.ts`
- Test: `frontend/src/chat/runtime.test.tsx`

**Interfaces:**
- Consumes: `useChatStream` return (Task 6), `convertMessage` (Task 3), `useExternalStoreRuntime`/`AppendMessage` from `@assistant-ui/react`.
- Produces: `useChatRuntime(opts: { messages, isRunning, onSend, onReload, onCancel }): AssistantRuntime` where `onSend(text: string): Promise<void>`. Wraps assistant-ui's `onNew` (extracts text from `AppendMessage`) and forwards the rest.

- [ ] **Step 1: Write the failing test.**

```tsx
// frontend/src/chat/runtime.test.tsx
import { renderHook } from '@testing-library/react'
import { useChatRuntime } from './runtime'

test('builds a runtime and exposes append that calls onSend', async () => {
  const onSend = vi.fn().mockResolvedValue(undefined)
  const { result } = renderHook(() =>
    useChatRuntime({
      messages: [{ id: 'm1', role: 'user', content: 'hi', streaming: false }],
      isRunning: false,
      onSend,
      onReload: vi.fn(),
      onCancel: vi.fn(),
    }),
  )
  expect(result.current).toBeTruthy()
  await result.current.thread.append('hello')
  expect(onSend).toHaveBeenCalledWith('hello')
})
```

- [ ] **Step 2: Run to verify it fails.**

Run: `cd frontend && npx vitest run src/chat/runtime.test.tsx`
Expected: FAIL ("Cannot find module './runtime'").

- [ ] **Step 3: Implement `runtime.ts`.**

```ts
// frontend/src/chat/runtime.ts
/** Bridge our chat store to assistant-ui via ExternalStoreRuntime. */
import { useExternalStoreRuntime, type AppendMessage } from '@assistant-ui/react'
import { convertMessage } from './convertMessage'
import type { ChatMessage } from './useChatStream'

function textOf(message: AppendMessage): string {
  const part = message.content[0]
  return part?.type === 'text' ? part.text : ''
}

export function useChatRuntime(opts: {
  messages: ChatMessage[]
  isRunning: boolean
  onSend: (text: string) => Promise<void>
  onReload: () => Promise<void>
  onCancel: () => void
}) {
  return useExternalStoreRuntime({
    messages: opts.messages,
    isRunning: opts.isRunning,
    convertMessage,
    onNew: async (message: AppendMessage) => {
      await opts.onSend(textOf(message))
    },
    onReload: async () => {
      await opts.onReload()
    },
    onCancel: async () => {
      opts.onCancel()
    },
  })
}
```

Note: `result.current.thread.append(...)` in the test uses the runtime's public API. If the installed version exposes append differently (e.g. `result.current.thread.getState()` / a different method), adjust the test to call the documented append path; the behavior under test is "append → onSend(text)".

- [ ] **Step 4: Run to verify it passes.**

Run: `cd frontend && npx vitest run src/chat/runtime.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add frontend/src/chat/runtime.ts frontend/src/chat/runtime.test.tsx
git commit -m "feat(frontend): ExternalStoreRuntime bridge for the chat store"
```

---

### Task 8: Thread component (primitives + markdown + actions + autoscroll)

**Files:**
- Create: `frontend/src/components/Thread.tsx`
- Create: `frontend/src/components/Thread.module.css`
- Test: `frontend/src/components/Thread.test.tsx`

**Interfaces:**
- Consumes: `ThreadPrimitive`, `MessagePrimitive`, `ActionBarPrimitive` from `@assistant-ui/react`; `MarkdownText` (Task 5); `CapyLogo`.
- Produces: `Thread()` — renders the message list (user bubble right, assistant row with glyph + markdown), an assistant action bar (Copy + Reload), and a ScrollToBottom affordance. Must be mounted inside an `AssistantRuntimeProvider`.

- [ ] **Step 1: Write the failing test.** Mount `Thread` under a real runtime seeded with one user + one assistant message.

```tsx
// frontend/src/components/Thread.test.tsx
import { render, screen } from '@testing-library/react'
import { AssistantRuntimeProvider } from '@assistant-ui/react'
import { renderHook } from '@testing-library/react'
import { useChatRuntime } from '../chat/runtime'
import { Thread } from './Thread'

function seed() {
  const { result } = renderHook(() =>
    useChatRuntime({
      messages: [
        { id: 'u1', role: 'user', content: 'Вопрос', streaming: false },
        { id: 'a1', role: 'assistant', content: '**Ответ** с `кодом`', streaming: false },
      ],
      isRunning: false,
      onSend: vi.fn().mockResolvedValue(undefined),
      onReload: vi.fn().mockResolvedValue(undefined),
      onCancel: vi.fn(),
    }),
  )
  return result.current
}

test('renders user and assistant messages with markdown', () => {
  const runtime = seed()
  render(
    <AssistantRuntimeProvider runtime={runtime}>
      <Thread />
    </AssistantRuntimeProvider>,
  )
  expect(screen.getByText('Вопрос')).toBeInTheDocument()
  expect(screen.getByText('Ответ')).toBeInTheDocument() // bold rendered
})
```

- [ ] **Step 2: Run to verify it fails.**

Run: `cd frontend && npx vitest run src/components/Thread.test.tsx`
Expected: FAIL ("Cannot find module './Thread'").

- [ ] **Step 3: Implement `Thread.tsx`.** Verify the exact primitive prop names against the reference captured in Task 2 before finalizing.

```tsx
// frontend/src/components/Thread.tsx
/** Active chat thread: message list, markdown assistant content, actions, autoscroll. */
import { ThreadPrimitive, MessagePrimitive, ActionBarPrimitive } from '@assistant-ui/react'
import { ArrowDown, Copy, RefreshCw } from 'lucide-react'
import { CapyLogo } from './CapyLogo'
import { MarkdownText } from './MessageMarkdown'
import styles from './Thread.module.css'

function UserMessage() {
  return (
    <MessagePrimitive.Root className={styles.userRow}>
      <div className={styles.bubble}>
        <MessagePrimitive.Content />
      </div>
    </MessagePrimitive.Root>
  )
}

function AssistantMessage() {
  return (
    <MessagePrimitive.Root className={styles.assistantRow}>
      <div className={styles.avatar}>
        <CapyLogo size={30} />
      </div>
      <div className={styles.assistantContent}>
        <MessagePrimitive.Content components={{ Text: MarkdownText }} />
        <ActionBarPrimitive.Root className={styles.actions}>
          <ActionBarPrimitive.Copy className={styles.actionBtn}>
            <Copy size={15} />
          </ActionBarPrimitive.Copy>
          <ActionBarPrimitive.Reload className={styles.actionBtn}>
            <RefreshCw size={15} />
          </ActionBarPrimitive.Reload>
        </ActionBarPrimitive.Root>
      </div>
    </MessagePrimitive.Root>
  )
}

export function Thread() {
  return (
    <ThreadPrimitive.Root className={styles.root}>
      <ThreadPrimitive.Viewport className={styles.viewport}>
        <div className={styles.inner}>
          <ThreadPrimitive.Messages components={{ UserMessage, AssistantMessage }} />
        </div>
        <ThreadPrimitive.ScrollToBottom className={styles.scrollBtn}>
          <ArrowDown size={16} />
        </ThreadPrimitive.ScrollToBottom>
      </ThreadPrimitive.Viewport>
    </ThreadPrimitive.Root>
  )
}
```

- [ ] **Step 4: Implement `Thread.module.css`** (port the bubble/row/caret styles from `Message.module.css`, add viewport + scroll-button).

```css
/* frontend/src/components/Thread.module.css */
.root { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.viewport { flex: 1; overflow-y: auto; padding: 22px; position: relative; }
.inner { max-width: 760px; margin: 0 auto; width: 100%; display: flex; flex-direction: column; gap: 22px; }
.userRow { display: flex; justify-content: flex-end; }
.bubble { max-width: 75%; padding: 10px 14px; border-radius: 15px 15px 4px 15px; font-size: 14.5px; line-height: 1.55; border: 1px solid rgba(216, 155, 108, 0.25); background: linear-gradient(160deg, rgba(216, 155, 108, 0.2), rgba(216, 155, 108, 0.12)); color: var(--text-primary, #f2ece4); }
.assistantRow { display: flex; gap: 12px; align-items: flex-start; }
.avatar { flex-shrink: 0; margin-top: 2px; }
.assistantContent { max-width: 75%; padding-top: 2px; }
.actions { display: flex; gap: 6px; margin-top: 8px; opacity: 0; transition: opacity 0.12s; }
.assistantRow:hover .actions { opacity: 1; }
.actionBtn { width: 30px; height: 30px; display: inline-flex; align-items: center; justify-content: center; border: 1px solid rgba(255, 255, 255, 0.09); border-radius: 8px; background: none; color: #a29a90; cursor: pointer; }
.actionBtn:hover { background: rgba(255, 255, 255, 0.06); color: #d6cdc3; }
.scrollBtn { position: absolute; bottom: 16px; left: 50%; transform: translateX(-50%); width: 34px; height: 34px; border-radius: 50%; border: 1px solid rgba(255, 255, 255, 0.1); background: rgba(38, 33, 28, 0.9); color: #d6cdc3; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; }
```

- [ ] **Step 5: Run to verify it passes.**

Run: `cd frontend && npx vitest run src/components/Thread.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add frontend/src/components/Thread.tsx frontend/src/components/Thread.module.css frontend/src/components/Thread.test.tsx
git commit -m "feat(frontend): assistant-ui Thread with markdown, actions, autoscroll"
```

---

### Task 9: Rework Composer onto ComposerPrimitive

**Files:**
- Modify: `frontend/src/components/Composer.tsx`
- Modify: `frontend/src/components/Composer.module.css` (only if new elements need styles)
- Test: `frontend/src/components/Composer.test.tsx`

**Interfaces:**
- Consumes: `ComposerPrimitive`, `ThreadPrimitive` from `@assistant-ui/react`; must render inside an `AssistantRuntimeProvider`.
- Produces: `Composer({ models, selectedModel, onSelectModel })` — the model pill + tools + send/cancel bound to the runtime. `onSend`/`disabled`/`initialText` props are **removed** (send now goes through the runtime's `onNew`; running state from the runtime).

- [ ] **Step 1: Update the failing tests.** The composer now needs a runtime context. Replace the prop-driven tests with runtime-backed ones asserting: typing + Send calls the runtime `onSend`; send is blocked without a valid model; selecting a model calls `onSelectModel`.

```tsx
// frontend/src/components/Composer.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AssistantRuntimeProvider } from '@assistant-ui/react'
import { renderHook } from '@testing-library/react'
import { useChatRuntime } from '../chat/runtime'
import { Composer } from './Composer'

const MODELS = ['llama3.1:8b', 'qwen2.5:14b']

function withRuntime(ui: (onSend: ReturnType<typeof vi.fn>) => React.ReactNode) {
  const onSend = vi.fn().mockResolvedValue(undefined)
  const { result } = renderHook(() =>
    useChatRuntime({ messages: [], isRunning: false, onSend, onReload: vi.fn(), onCancel: vi.fn() }),
  )
  render(<AssistantRuntimeProvider runtime={result.current}>{ui(onSend)}</AssistantRuntimeProvider>)
  return onSend
}

test('Send routes text through the runtime onSend', async () => {
  const onSend = withRuntime(() => (
    <Composer models={MODELS} selectedModel="llama3.1:8b" onSelectModel={vi.fn()} />
  ))
  await userEvent.type(screen.getByRole('textbox'), 'Привет')
  await userEvent.click(screen.getByLabelText('Отправить'))
  expect(onSend).toHaveBeenCalledWith('Привет')
})

test('send disabled without a valid model', () => {
  withRuntime(() => <Composer models={MODELS} selectedModel={null} onSelectModel={vi.fn()} />)
  expect(screen.getByLabelText('Отправить')).toBeDisabled()
})

test('selecting a model calls onSelectModel', async () => {
  const onSelectModel = vi.fn()
  withRuntime(() => <Composer models={MODELS} selectedModel="llama3.1:8b" onSelectModel={onSelectModel} />)
  await userEvent.selectOptions(screen.getByRole('combobox'), 'qwen2.5:14b')
  expect(onSelectModel).toHaveBeenCalledWith('qwen2.5:14b')
})
```

- [ ] **Step 2: Run to verify they fail.**

Run: `cd frontend && npx vitest run src/components/Composer.test.tsx`
Expected: FAIL (Composer still uses the old prop API / no runtime).

- [ ] **Step 3: Reimplement `Composer.tsx`.** Model pill stays a custom child; `ComposerPrimitive.Send` is disabled when no valid model (compose the `disabled` prop). Send/Cancel swap via `ThreadPrimitive.If running`.

```tsx
// frontend/src/components/Composer.tsx
/** Runtime-bound composer: auto-grow input, model selector, tools (visual), send/cancel. */
import { ComposerPrimitive, ThreadPrimitive } from '@assistant-ui/react'
import { ArrowUp, Paperclip, Square } from 'lucide-react'
import styles from './Composer.module.css'

export function Composer({
  models,
  selectedModel,
  onSelectModel,
}: {
  models: string[]
  selectedModel: string | null
  onSelectModel: (m: string) => void
}) {
  const modelValid = selectedModel !== null && models.includes(selectedModel)
  return (
    <ComposerPrimitive.Root className={styles.composer}>
      <ComposerPrimitive.Input
        className={styles.input}
        rows={1}
        autoFocus
        placeholder="Спросите что-нибудь…"
        submitOnEnter
      />
      <div className={styles.row}>
        <button type="button" className={styles.iconBtn} disabled tabIndex={-1} aria-hidden="true">
          <Paperclip size={18} />
        </button>
        <select
          className={`${styles.modelSelect} ${modelValid ? '' : styles.modelSelectInvalid}`}
          aria-label="Модель"
          value={modelValid ? (selectedModel as string) : ''}
          onChange={(e) => onSelectModel(e.target.value)}
        >
          <option value="" disabled>Выберите модель</option>
          {models.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
        <div className={styles.spacer} />
        <ThreadPrimitive.If running={false}>
          <ComposerPrimitive.Send className={styles.send} aria-label="Отправить" disabled={!modelValid}>
            <ArrowUp size={18} />
          </ComposerPrimitive.Send>
        </ThreadPrimitive.If>
        <ThreadPrimitive.If running>
          <ComposerPrimitive.Cancel className={styles.send} aria-label="Остановить">
            <Square size={16} />
          </ComposerPrimitive.Cancel>
        </ThreadPrimitive.If>
      </div>
    </ComposerPrimitive.Root>
  )
}
```

Note: confirm `ComposerPrimitive.Input` accepts `submitOnEnter` and that `ComposerPrimitive.Send` forwards `disabled` in the installed version (Task 2 reference). If `Send` does not forward `disabled`, gate submission by rendering `Send` only when `modelValid`, and show a disabled stand-in otherwise.

- [ ] **Step 4: Run to verify they pass.**

Run: `cd frontend && npx vitest run src/components/Composer.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add frontend/src/components/Composer.tsx frontend/src/components/Composer.module.css frontend/src/components/Composer.test.tsx
git commit -m "feat(frontend): ComposerPrimitive-based composer with model pill and cancel"
```

---

### Task 10: Wire ChatScreen to the runtime

**Files:**
- Modify: `frontend/src/screens/ChatScreen.tsx`
- Modify: `frontend/src/screens/ChatScreen.module.css` (remove now-unused `.thread`/`.threadInner` if replaced by `Thread`)
- Delete: `frontend/src/components/Message.tsx`, `frontend/src/components/Message.module.css` (replaced by `Thread`)
- Test: `frontend/src/screens/ChatScreen.test.tsx`

**Interfaces:**
- Consumes: `useChatRuntime` (Task 7), `Thread` (Task 8), reworked `Composer` (Task 9), `AssistantRuntimeProvider`.
- Produces: `ChatScreen` mounting one runtime (welcome + active), driving send/regenerate/cancel through it.

- [ ] **Step 1: Adapt the existing tests.** The two current tests in `ChatScreen.test.tsx` already exercise the right behavior and their queries survive the rework (`getByRole('textbox')` → `ComposerPrimitive.Input`; `getByLabelText('Отправить')` → our Send; `getByLabelText('Модель')` → the select). Keep test 1 (`welcome greets... streams a reply`) **as-is** — it types `'Привет{Enter}'` (works via `ComposerPrimitive.Input submitOnEnter`) and asserts `findByText('Здравствуйте')` (now rendered through `MarkdownText`, still findable in the `<p>`).

  **One required change** to test 2 (`blocks send until a model is valid`): `ComposerPrimitive.Send` also gates on **non-empty input**, so asserting the button enables with an empty textarea will fail. Type text first:

```tsx
  await userEvent.selectOptions(screen.getByLabelText('Модель'), 'llama3.1:8b')
  await userEvent.type(screen.getByRole('textbox'), 'Привет')   // Send also needs non-empty text
  expect(sendBtn).not.toBeDisabled()
```

  Add a third test for the loading state: mock `GET /api/chats/:id` to delay, select the chat, and assert a loading indicator (`getByText(/загрузка|загружаем/i)` or `getByRole('status')`) appears then clears once messages render.

- [ ] **Step 2: Run to verify it fails.**

Run: `cd frontend && npx vitest run src/screens/ChatScreen.test.tsx`
Expected: FAIL (Composer prop mismatch / Thread not wired).

- [ ] **Step 3: Reimplement `ChatScreen.tsx`.** Build the runtime from the store; provide `onSend` that creates a chat if none is active (using `chatIdOverride` on `send`), preserving the model-selection logic; render `Thread` + `Composer` inside the provider.

```tsx
// frontend/src/screens/ChatScreen.tsx (key structure)
import { useEffect, useState } from 'react'
import { AssistantRuntimeProvider } from '@assistant-ui/react'
import { CapyLogo } from '../components/CapyLogo'
import { Composer } from '../components/Composer'
import { Thread } from '../components/Thread'
import { Sidebar } from '../components/Sidebar'
import { useAuth, useApiClient } from '../auth/AuthContext'
import { useChats } from '../chat/useChats'
import { useModels } from '../chat/useModels'
import { useChatStream } from '../chat/useChatStream'
import { useChatRuntime } from '../chat/runtime'
import { patchChatModel } from '../chat/chatApi'
import { loadLastModel, saveLastModel } from '../chat/lastModel'
import styles from './ChatScreen.module.css'

const CHIPS = [
  { emoji: '✍️', label: 'Написать текст' },
  { emoji: '🔍', label: 'Найти информацию' },
  { emoji: '💡', label: 'Придумать идею' },
  { emoji: '📝', label: 'Суммаризировать' },
]

export function ChatScreen() {
  const { user } = useAuth()
  const api = useApiClient()
  const [activeChatId, setActiveChatId] = useState<string | null>(null)
  const [draftModel, setDraftModel] = useState<string | null>(() => loadLastModel())
  const { chats, reload, newChat } = useChats()
  const { models } = useModels()
  const { messages, sending, loadingHistory, send, loadHistory, regenerate, cancel } = useChatStream(activeChatId)

  useEffect(() => { void loadHistory() }, [loadHistory])

  const activeChat = chats.find((c) => c.id === activeChatId)
  const selectedModel = activeChatId ? (activeChat?.model ?? null) : draftModel

  async function handleSend(text: string) {
    if (activeChatId) {
      await send(text)
      await reload()
      return
    }
    const chat = await newChat(draftModel ?? undefined)
    setActiveChatId(chat.id)
    await send(text, chat.id) // chatId-safe send (Task 6)
    await reload()
  }

  const runtime = useChatRuntime({
    messages,
    isRunning: sending,
    onSend: handleSend,
    onReload: regenerate,
    onCancel: cancel,
  })

  async function handleSelectModel(model: string) {
    saveLastModel(model)
    setDraftModel(model)
    if (activeChatId) { await patchChatModel(api, activeChatId, model); await reload() }
  }

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className={styles.screen}>
        <Sidebar chats={chats} activeChatId={activeChatId} onSelect={setActiveChatId} onNewChat={() => setActiveChatId(null)} />
        <main className={styles.main}>
          {activeChatId === null ? (
            <div className={styles.welcome}>
              <div className={styles.welcomeContent}>
                <CapyLogo size={78} />
                <h1 className={styles.greeting}>Чем помочь, {user?.displayName ?? 'пользователь'}?</h1>
                <p className={styles.subtitle}>Задайте вопрос или выберите подсказку ниже.</p>
                <Composer models={models} selectedModel={selectedModel} onSelectModel={handleSelectModel} />
                <div className={styles.chips}>
                  {CHIPS.map((c) => (
                    <button key={c.label} type="button" className={styles.chip}>{c.emoji} {c.label}</button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className={styles.active}>
              <header className={styles.header}>
                <span className={styles.chatTitle}>{activeChat?.title ?? 'Чат'}</span>
              </header>
              {loadingHistory && messages.length === 0 ? (
                <div className={styles.loading} role="status">Загрузка…</div>
              ) : (
                <Thread />
              )}
              <div className={styles.composerArea}>
                <div className={styles.composerMaxWidth}>
                  <Composer models={models} selectedModel={selectedModel} onSelectModel={handleSelectModel} />
                </div>
              </div>
            </div>
          )}
        </main>
      </div>
    </AssistantRuntimeProvider>
  )
}
```

Add to `ChatScreen.module.css`:
```css
.loading { flex: 1; display: flex; align-items: center; justify-content: center; color: #a29a90; font-size: 14px; }
```

Notes:
- The old deferred `pendingSend`/`skipNextHistory` mechanism is removed: `send(text, chat.id)` now targets the new chat directly (Task 6), and `loadHistory` for the just-created chat is harmless (empty) — but if a race overwrites streamed messages, gate `loadHistory` to skip when messages already exist for the active chat.
- Chip click prefill: if desired, keep a small local state feeding `ComposerPrimitive` initial text via the runtime composer API; otherwise chips can be deferred (not a success criterion). Keep behavior parity with the current build.

- [ ] **Step 4: Delete the retired Message component.**

Run: `git rm frontend/src/components/Message.tsx frontend/src/components/Message.module.css frontend/src/components/Message.test.tsx`
(If `Message.test.tsx` does not exist, omit it.)

- [ ] **Step 5: Run the screen tests to verify they pass.**

Run: `cd frontend && npx vitest run src/screens/ChatScreen.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add frontend/src/screens/ChatScreen.tsx frontend/src/screens/ChatScreen.module.css frontend/src/screens/ChatScreen.test.tsx
git commit -m "feat(frontend): mount assistant-ui runtime in ChatScreen; retire Message"
```

---

### Task 11: Full-suite gates + manual verification

**Files:** none (verification only).

- [ ] **Step 1: Run the whole frontend suite.**

Run: `cd frontend && npm run test`
Expected: all tests PASS.

- [ ] **Step 2: Lint, type-check, build.**

Run: `cd frontend && npm run lint && npm run typecheck && npm run build`
Expected: all PASS with no warnings (lint is `--max-warnings 0`).

- [ ] **Step 3: Manual success-criteria walkthrough** (backend + Ollama running, `npm run dev`):
  - Send a message → reply **streams** and renders; a markdown **table**, a **list**, and a **highlighted code block** format correctly; the code block **copies** on click.
  - History renders on chat select and on page reload; the thread **auto-scrolls** to the newest message while streaming.
  - Trigger a stream error (e.g. stop Ollama) → an in-thread error row with a retry; **Cancel** stops an in-flight reply.
  - **Copy message** and **Regenerate** work on an assistant reply.
  - Paste a model reply containing `<script>` (or use a fixture) → it is **sanitized** (no execution).
  - UI still matches the handoff (glass, accent, typography, radii).

- [ ] **Step 4: Final commit if any lint/format fixups were needed.**

```bash
git add -u frontend
git commit -m "chore(frontend): lint/format fixups for chat rendering slice"
```

---

## Notes for the executor

- **assistant-ui version drift:** Tasks 7–9 use documented primitive names (`ThreadPrimitive`, `MessagePrimitive`, `ActionBarPrimitive`, `ComposerPrimitive`) and `useExternalStoreRuntime`. Before implementing each, cross-check the exact prop/import names against the version installed in Task 2 (docs pages: runtimes/custom/external-store, ui/Markdown, primitives/composer, ui/Thread). Adjust JSX to match; the tests pin behavior, not internal prop spelling.
- **`convertMessage` is the single extension seam:** future tool-call/artifact/citation slices add `MessagePart` variants (Task 3) + branches in `convertMessage` + new renderers registered via `MessagePrimitive.Content components={{ ... }}`. No thread/composer rewrite needed.
- Keep each commit scoped to its own files (concurrent user commits).
