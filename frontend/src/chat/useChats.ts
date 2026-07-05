import { useCallback, useEffect, useState } from 'react'
import { useApiClient } from '../auth/AuthContext'
import type { ChatOut } from '../api/types'
import { createChat, listChats } from './chatApi'

export function useChats() {
  const api = useApiClient()
  const [chats, setChats] = useState<ChatOut[]>([])
  const [loading, setLoading] = useState(true)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      setChats(await listChats(api))
    } finally {
      setLoading(false)
    }
  }, [api])

  useEffect(() => {
    void reload()
  }, [reload])

  const newChat = useCallback(
    async (model?: string) => {
      const chat = await createChat(api, undefined, model)
      setChats((prev) => [chat, ...prev])
      return chat
    },
    [api],
  )

  const patchLocal = useCallback((id: string, fields: Partial<ChatOut>) => {
    setChats((prev) => prev.map((c) => (c.id === id ? { ...c, ...fields } : c)))
  }, [])

  const removeLocal = useCallback((id: string) => {
    setChats((prev) => prev.filter((c) => c.id !== id))
  }, [])

  return { chats, loading, reload, newChat, patchLocal, removeLocal }
}
