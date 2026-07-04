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
