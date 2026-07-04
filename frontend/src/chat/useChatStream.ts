import { useCallback, useRef, useState } from 'react'
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

  // Render-time ref updates: always reflect the latest value without requiring
  // effects or adding to dependency arrays.
  const chatIdRef = useRef(chatId)
  chatIdRef.current = chatId

  const messagesRef = useRef<ChatMessage[]>([])
  messagesRef.current = messages

  const abortRef = useRef<AbortController | null>(null)

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
        for await (const ev of parseSse(res.body, controller.signal)) {
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
          patch((m) => ({ ...m, streaming: false, error: true, content: 'Ошибка при получении ответа.' }))
        }
      } finally {
        setSending(false)
        abortRef.current = null
      }
    },
    [api],
  )

  /** Aborts any in-flight stream, settling the assistant message without marking it as an error. */
  const cancel = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  /**
   * Drops the last assistant message and re-sends the last user message.
   *
   * Reads the current messages snapshot via a ref so that the latest value is
   * available synchronously (avoids depending on the setState updater being
   * called before the surrounding async function continues).
   */
  const regenerate = useCallback(async () => {
    const currentMessages = messagesRef.current
    const lastUser = [...currentMessages].reverse().find((m) => m.role === 'user')
    const lastAssistantIdx = currentMessages.map((m) => m.role).lastIndexOf('assistant')
    if (lastAssistantIdx !== -1) {
      setMessages((prev) => prev.filter((_, i) => i !== lastAssistantIdx))
    }
    if (lastUser) await send(lastUser.content)
  }, [send])

  return { messages, sending, loadingHistory, send, loadHistory, cancel, regenerate }
}
