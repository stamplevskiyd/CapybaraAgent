/** Translate our ChatMessage into assistant-ui's parts-based ThreadMessageLike. */
import type { ThreadMessageLike } from '@assistant-ui/react'
import type { ChatMessage } from './useChatStream'

export function convertMessage(m: ChatMessage): ThreadMessageLike {
  return {
    id: m.id,
    role: m.role,
    // Empty text ⇒ no parts, so assistant-ui reports hasContent=false. The Thread shows a
    // typing indicator on the last empty+running assistant message (before its first token).
    content: m.content ? [{ type: 'text', text: m.content }] : [],
    status: m.streaming ? { type: 'running' } : undefined,
  }
}
