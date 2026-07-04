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

  const newChat = useCallback(async () => {
    const chat = await createChat(api)
    setChats((prev) => [chat, ...prev])
    return chat
  }, [api])

  return { chats, loading, reload, newChat }
}
