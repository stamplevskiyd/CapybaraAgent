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
  created_at: string
  updated_at: string
}

export interface MessageOut {
  id: string
  role: string
  content: string
  model: string | null
  incomplete: boolean
  created_at: string
}

export type ChatDetailOut = ChatOut & { messages: MessageOut[] }
