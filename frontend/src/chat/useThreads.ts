/** Sidebar thread list: Chainlit's persisted threads merged with per-thread prefs. */
import { useCallback, useEffect, useState } from 'react'
import { useApiClient } from '../auth/AuthContext'
import type { ChatOut } from '../api/types'
import { chainlitClient } from '../chainlit/client'
import { listChatPrefs } from './chatPrefs'

/** How many threads the sidebar fetches (no pagination UI yet). */
const THREAD_PAGE_SIZE = 200

function toIso(createdAt: number | string): string {
  return typeof createdAt === 'number' ? new Date(createdAt).toISOString() : createdAt
}

/**
 * Load the user's chat list: Chainlit owns the threads (id, name, createdAt); the
 * favorite flag and selected model ride in Capybara's chat-prefs, joined by thread id.
 *
 * `reload` is safe to call before the Chainlit session is authenticated — a failed
 * fetch keeps the current list, and the caller re-reloads once connected.
 */
export function useThreads() {
  const api = useApiClient()
  const [chats, setChats] = useState<ChatOut[]>([])
  const [loading, setLoading] = useState(true)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const [threads, prefs] = await Promise.all([
        chainlitClient.listThreads({ first: THREAD_PAGE_SIZE }, {}),
        listChatPrefs(api),
      ])
      const prefByThread = new Map(prefs.map((p) => [p.thread_id, p]))
      setChats(
        threads.data.map((thread) => {
          const pref = prefByThread.get(thread.id)
          const createdAt = toIso(thread.createdAt)
          return {
            id: thread.id,
            title: thread.name ?? 'Новый чат',
            model: pref?.model ?? null,
            is_favorite: pref?.is_favorite ?? false,
            created_at: createdAt,
            updated_at: createdAt,
          }
        }),
      )
    } catch {
      // Pre-auth or transient failure: keep the current list; the next reload syncs it.
    } finally {
      setLoading(false)
    }
  }, [api])

  useEffect(() => {
    void reload()
  }, [reload])

  const patchLocal = useCallback((id: string, fields: Partial<ChatOut>) => {
    setChats((prev) => prev.map((c) => (c.id === id ? { ...c, ...fields } : c)))
  }, [])

  const removeLocal = useCallback((id: string) => {
    setChats((prev) => prev.filter((c) => c.id !== id))
  }, [])

  return { chats, loading, reload, patchLocal, removeLocal }
}
