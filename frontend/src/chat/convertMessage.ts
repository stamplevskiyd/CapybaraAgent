/** Translate our ChatMessage into assistant-ui's parts-based ThreadMessageLike. */
import type { ThreadMessageLike } from '@assistant-ui/react'
import type { ChatMessage } from './useChatStream'

export function convertMessage(m: ChatMessage): ThreadMessageLike {
  return {
    id: m.id,
    role: m.role,
    content: [{ type: 'text', text: m.content }],
    status: m.streaming ? { type: 'running' } : undefined,
  }
}
