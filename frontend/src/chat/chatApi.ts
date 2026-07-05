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
export const deleteChat = (api: ApiClient, id: string) => api.del(`/chats/${id}`)
export const renameChat = (api: ApiClient, id: string, title: string) =>
  api.patch<ChatOut>(`/chats/${id}`, { title })
export const setFavorite = (api: ApiClient, id: string, isFavorite: boolean) =>
  api.patch<ChatOut>(`/chats/${id}`, { is_favorite: isFavorite })
