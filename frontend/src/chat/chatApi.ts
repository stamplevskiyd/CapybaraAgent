import type { ApiClient } from '../api/client'
import type { ChatDetailOut, ChatOut, ModelsOut } from '../api/types'

export const listChats = (api: ApiClient) => api.get<ChatOut[]>('/chats')
export const createChat = (api: ApiClient, title?: string, model?: string) =>
  api.post<ChatOut>('/chats', { title: title ?? null, model: model ?? null })
export const getChat = (api: ApiClient, id: string) =>
  api.get<ChatDetailOut>(`/chats/${id}`)
export const listModels = (api: ApiClient) => api.get<ModelsOut>('/models')
export const patchChatModel = (api: ApiClient, id: string, model: string) =>
  api.patch<ChatOut>(`/chats/${id}`, { model })
