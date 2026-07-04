import type { ApiClient } from '../api/client'
import type { ChatDetailOut, ChatOut } from '../api/types'

export const listChats = (api: ApiClient) => api.get<ChatOut[]>('/chats')
export const createChat = (api: ApiClient, title?: string) =>
  api.post<ChatOut>('/chats', { title: title ?? null })
export const getChat = (api: ApiClient, id: string) =>
  api.get<ChatDetailOut>(`/chats/${id}`)
