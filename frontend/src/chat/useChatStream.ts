/** Chat message store: history load + live SSE streaming, cancel, and regenerate. */
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
export function useChatStream(chatId: string | null, onTitle?: (title: string) => void) {
  const api = useApiClient()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [sending, setSending] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)

  // Render-time ref updates: always reflect the latest value without requiring
  // effects or adding to dependency arrays.
  const chatIdRef = useRef(chatId)
  chatIdRef.current = chatId

  const onTitleRef = useRef(onTitle)
  onTitleRef.current = onTitle

  const abortRef = useRef<AbortController | null>(null)
  // The chat a running stream belongs to, so navigating away can abort it while
  // the initial create-and-send flow (which points the stream at the newly
  // active chat) is left untouched.
  const streamingChatIdRef = useRef<string | null>(null)

  // Abort an in-flight stream when the user navigates to a different chat; the
  // orphaned stream would otherwise keep the composer stuck in the running state.
  useEffect(() => {
    const controller = abortRef.current
    if (controller && streamingChatIdRef.current !== chatId) controller.abort()
  }, [chatId])

  // Abort on unmount (e.g. logout) so a backgrounded stream never updates a dead component.
  useEffect(() => () => abortRef.current?.abort(), [])

  /** Loads the chat history and initializes the message list. */
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

  /**
   * Shared SSE streaming helper used by both `send` and `regenerate`.
   *
   * Opens a POST SSE stream to `url` with `body`, patches the assistant message
   * identified by `assistantId` with incoming delta/done/error events, and
   * handles abort and error semantics consistently:
   * - Abort (cancel) settles the message without marking it as an error.
   * - Network or API errors set `error: true` with a generic message.
   * - `sending` is set to `true` for the duration and `false` on completion.
   *
   * @param targetChatId - Chat the stream belongs to; lets a chat switch abort it.
   * @param assistantId - Local ID of the assistant message row to patch.
   * @param url - API path to POST to (e.g. `/chats/${id}/messages`).
   * @param body - Request body; pass `{}` for endpoints that take no meaningful body
   *   (api.stream JSON.stringifies every body, so `{}` → `"{}"` which FastAPI ignores).
   */
  const streamAssistant = useCallback(
    async (targetChatId: string, assistantId: string, url: string, body: unknown) => {
      const patch = (fn: (m: ChatMessage) => ChatMessage) =>
        setMessages((prev) => prev.map((m) => (m.id === assistantId ? fn(m) : m)))
      const controller = new AbortController()
      abortRef.current = controller
      streamingChatIdRef.current = targetChatId
      setSending(true)
      try {
        const res = await api.stream(url, body, controller.signal)
        if (!res.body) throw new Error('no stream')
        for await (const ev of parseSse(res.body, controller.signal)) {
          if (ev.event === 'delta') {
            const { text: delta } = JSON.parse(ev.data) as { text: string }
            patch((m) => ({ ...m, content: m.content + delta }))
          } else if (ev.event === 'done') {
            patch((m) => ({ ...m, streaming: false }))
            setSending(false)
          } else if (ev.event === 'error') {
            const { message } = JSON.parse(ev.data) as { message: string }
            patch((m) => ({ ...m, streaming: false, error: true, content: message }))
          } else if (ev.event === 'title') {
            const { title } = JSON.parse(ev.data) as { title: string }
            onTitleRef.current?.(title)
          }
        }
        // reader.cancel() from abort causes the loop to exit without throwing;
        // settle the message if that's what happened.
        if (controller.signal.aborted) {
          patch((m) => ({ ...m, streaming: false }))
        }
      } catch (err) {
        if (controller.signal.aborted) {
          // fetch itself was aborted before the response body started
          patch((m) => ({ ...m, streaming: false }))
        } else {
          patch((m) => ({
            ...m,
            streaming: false,
            error: true,
            content: 'Ошибка при получении ответа.',
          }))
        }
      } finally {
        // Only settle shared state if we're still the active stream — a newer send
        // may have taken over while this one drained its trailing title frame.
        if (abortRef.current === controller) {
          setSending(false)
          abortRef.current = null
          streamingChatIdRef.current = null
        }
      }
    },
    [api],
  )

  /** Sends a user message and streams the assistant reply via SSE. */
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
      await streamAssistant(id, assistantId, `/chats/${id}/messages`, { content: text })
    },
    [streamAssistant],
  )

  /** Aborts any in-flight stream, settling the assistant message without marking it as an error. */
  const cancel = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  /**
   * Drops the trailing assistant message (if present) and requests a fresh reply
   * from the backend via POST /chats/{id}/messages/regenerate.
   *
   * The backend uses the persisted last user message to regenerate, so no new user
   * row is created and no user bubble is appended here. Only the last message is
   * removed when it is an assistant — a user-only tail is left untouched.
   *
   * An empty body `{}` is sent because `api.stream` JSON-stringifies its body
   * argument; the FastAPI endpoint accepts a POST with no meaningful body and
   * ignores the `{}` payload.
   */
  const regenerate = useCallback(async () => {
    const id = chatIdRef.current
    if (!id) return
    const assistantId = localId()
    setMessages((prev) => {
      const last = prev[prev.length - 1]
      const withoutLast = last?.role === 'assistant' ? prev.slice(0, -1) : prev
      return [...withoutLast, { id: assistantId, role: 'assistant', content: '', streaming: true }]
    })
    await streamAssistant(id, assistantId, `/chats/${id}/messages/regenerate`, {})
  }, [streamAssistant])

  return { messages, sending, loadingHistory, send, loadHistory, cancel, regenerate }
}
