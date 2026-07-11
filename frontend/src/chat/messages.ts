/** Normalized chat message shapes shared by the Chainlit adapter and the assistant-ui bridge. */

export type ToolCallState = {
  id: string
  name: string
  args: Record<string, unknown>
  result?: string
  running: boolean
}

export type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  streaming: boolean
  error?: boolean
  toolCalls?: ToolCallState[]
}
