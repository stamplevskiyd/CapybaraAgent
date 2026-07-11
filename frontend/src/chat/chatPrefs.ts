/** REST helpers for per-thread chat preferences (favorite flag, selected model). */
import type { ApiClient } from '../api/client'
import type { ChatPrefOut } from '../api/types'

export const listChatPrefs = (api: ApiClient) => api.get<ChatPrefOut[]>('/chat-prefs')

export const putChatPref = (
  api: ApiClient,
  threadId: string,
  pref: { is_favorite: boolean; model: string | null },
) => api.put<ChatPrefOut>(`/chat-prefs/${threadId}`, pref)

export const deleteChatPref = (api: ApiClient, threadId: string) =>
  api.del(`/chat-prefs/${threadId}`)
