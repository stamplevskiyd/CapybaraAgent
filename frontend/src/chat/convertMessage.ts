/** Translate our ChatMessage into assistant-ui's parts-based ThreadMessageLike. */
import type { ThreadMessageLike } from '@assistant-ui/react'
import type { ReadonlyJSONObject } from 'assistant-stream/utils'
import type { ChatMessage } from './useChatStream'

export function convertMessage(m: ChatMessage): ThreadMessageLike {
  const toolParts = (m.toolCalls ?? []).map((t) => ({
    type: 'tool-call' as const,
    toolCallId: t.id,
    toolName: t.name,
    // ToolCallState.args is Record<string,unknown>; assistant-ui expects ReadonlyJSONObject.
    // Values are always JSON-safe at runtime; bridge the structural type gap.
    args: t.args as unknown as ReadonlyJSONObject,
    ...(t.result !== undefined ? { result: t.result } : {}),
  }))
  const textParts = m.content ? [{ type: 'text' as const, text: m.content }] : []
  return {
    id: m.id,
    role: m.role,
    // Tool-call parts render before the answer text; empty text ⇒ no text part, so
    // assistant-ui reports hasContent=false and the typing indicator can show.
    content: [...toolParts, ...textParts],
    status: m.streaming ? { type: 'running' } : undefined,
  }
}
