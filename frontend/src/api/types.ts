export type { AgentMode } from '../chat/messages'
import type { AgentMode } from '../chat/messages'

export interface UserOut {
  id: string
  username: string
  display_name: string
  created_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

/** Sidebar chat entry: a Chainlit thread merged with its per-thread prefs. */
export interface ChatOut {
  id: string
  title: string
  model: string | null
  is_favorite: boolean
  mode: AgentMode
  created_at: string
  updated_at: string
}

/** Per-thread preferences stored by Capybara (Chainlit has no concept of these). */
export interface ChatSettingsOut {
  thread_id: string
  is_favorite: boolean
  model: string | null
  mode: AgentMode
}

export interface ModelsOut {
  provider: string
  models: string[]
}

export type Category = 'personal' | 'project' | 'preference'

export interface FactOut {
  id: string
  category: Category
  content: string
  source: 'manual' | 'auto'
  created_at: string
  updated_at: string
}

export interface FactUpdate {
  content?: string
  category?: Category
}

export interface McpToolOut {
  id: string
  name: string
  description: string | null
  enabled: boolean
}

export interface McpServerOut {
  id: string
  name: string
  url: string
  enabled: boolean
  last_connected_at: string | null
  last_error: string | null
  created_at: string
  updated_at: string
  tools: McpToolOut[]
}
