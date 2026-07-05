/** Memory (facts) API calls over the shared authenticated ApiClient. */
import type { ApiClient } from '../api/client'
import type { Category, FactOut, FactUpdate, MemorySettings } from '../api/types'

export const listFacts = (api: ApiClient) => api.get<FactOut[]>('/memory/facts')

export const createFact = (api: ApiClient, content: string, category: Category) =>
  api.post<FactOut>('/memory/facts', { content, category })

export const updateFact = (api: ApiClient, id: string, patch: FactUpdate) =>
  api.patch<FactOut>(`/memory/facts/${id}`, patch)

export const deleteFact = (api: ApiClient, id: string) => api.del(`/memory/facts/${id}`)

export const getMemorySettings = (api: ApiClient) => api.get<MemorySettings>('/memory/settings')

export const patchMemorySettings = (api: ApiClient, autoCapture: boolean) =>
  api.patch<MemorySettings>('/memory/settings', { auto_capture: autoCapture })
