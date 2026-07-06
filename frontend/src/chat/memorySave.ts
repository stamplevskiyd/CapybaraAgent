/** Applies memory-save push events to the message list (immutably). */
import type { ChatMessage } from './useChatStream'

/** Shape of a `memory-save` SSE event payload. */
export type MemorySaveEvent = {
  chat_id: string
  message_id: string
  facts: { content: string; category: string }[]
}

/** Returns a new message list with `memorySaves` set on the event's target message. */
export function applyMemorySave(messages: ChatMessage[], evt: MemorySaveEvent): ChatMessage[] {
  return messages.map((m) => (m.id === evt.message_id ? { ...m, memorySaves: evt.facts } : m))
}
