import { useCallback, useEffect, useState } from 'react'
import { useApiClient } from '../auth/AuthContext'
import type { ModelsOut } from '../api/types'

/** Fetch the provider's available model names once, with a manual reload. */
export function useModels() {
  const api = useApiClient()
  const [models, setModels] = useState<string[]>([])

  const reloadModels = useCallback(async () => {
    try {
      const out = await api.get<ModelsOut>('/models')
      setModels(out.models)
    } catch {
      setModels([])
    }
  }, [api])

  useEffect(() => {
    void reloadModels()
  }, [reloadModels])

  return { models, reloadModels }
}
