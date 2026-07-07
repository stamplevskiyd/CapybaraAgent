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

export interface ChatOut {
  id: string
  title: string
  model: string | null
  is_favorite: boolean
  created_at: string
  updated_at: string
}

export interface ModelsOut {
  provider: string
  models: string[]
}

export interface ToolCallOut {
  id: string
  name: string
  args: Record<string, unknown>
  result: string | null
}

export interface MemorySaveOut {
  content: string
  category: string
}

export interface MessageOut {
  id: string
  role: string
  content: string
  model: string | null
  incomplete: boolean
  created_at: string
  tool_calls?: ToolCallOut[] | null
  memory_saves?: MemorySaveOut[] | null
}

export type ChatDetailOut = ChatOut & { messages: MessageOut[] }

export type Category = 'personal' | 'project' | 'preference'

export interface FactOut {
  id: string
  category: Category
  content: string
  source: 'manual' | 'auto'
  created_at: string
  updated_at: string
}

export interface FactCreate {
  content: string
  category: Category
}

export interface FactUpdate {
  content?: string
  category?: Category
}

export interface MemorySettings {
  auto_capture: boolean
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

export interface McpServerCreate {
  name: string
  url: string
  headers?: Record<string, string>
}
