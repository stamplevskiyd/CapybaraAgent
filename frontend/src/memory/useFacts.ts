/** Facts + auto-capture state with optimistic mutations reconciled from the server on failure. */
import { useCallback, useEffect, useState } from 'react'
import { useApiClient } from '../auth/AuthContext'
import type { Category, FactOut, FactUpdate } from '../api/types'
import {
  createFact,
  deleteFact,
  getMemorySettings,
  listFacts,
  patchMemorySettings,
  updateFact,
} from './memoryApi'

/**
 * Load and mutate the current user's facts and the auto-capture toggle.
 *
 * Mutations update local state optimistically; on failure the list (or toggle) is
 * re-synced from the server via `reload`, so the UI never drifts from persisted state.
 */
export function useFacts() {
  const api = useApiClient()
  const [facts, setFacts] = useState<FactOut[]>([])
  const [autoCapture, setAutoCapture] = useState(true)
  const [loading, setLoading] = useState(true)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const [f, s] = await Promise.all([listFacts(api), getMemorySettings(api)])
      setFacts(f)
      setAutoCapture(s.auto_capture)
    } finally {
      setLoading(false)
    }
  }, [api])

  useEffect(() => {
    void reload()
  }, [reload])

  const addFact = useCallback(
    async (content: string, category: Category) => {
      const created = await createFact(api, content, category)
      setFacts((prev) => [created, ...prev])
      return created
    },
    [api],
  )

  const editFact = useCallback(
    async (id: string, patch: FactUpdate) => {
      setFacts((prev) => prev.map((f) => (f.id === id ? { ...f, ...patch } : f)))
      try {
        const updated = await updateFact(api, id, patch)
        setFacts((prev) => prev.map((f) => (f.id === id ? updated : f)))
      } catch {
        await reload()
      }
    },
    [api, reload],
  )

  const removeFact = useCallback(
    async (id: string) => {
      setFacts((prev) => prev.filter((f) => f.id !== id))
      try {
        await deleteFact(api, id)
      } catch {
        await reload()
      }
    },
    [api, reload],
  )

  const toggleAutoCapture = useCallback(
    async (value: boolean) => {
      setAutoCapture(value)
      try {
        const s = await patchMemorySettings(api, value)
        setAutoCapture(s.auto_capture)
      } catch {
        await reload()
      }
    },
    [api, reload],
  )

  return { facts, autoCapture, loading, reload, addFact, editFact, removeFact, toggleAutoCapture }
}
