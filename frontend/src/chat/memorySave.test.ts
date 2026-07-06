import { describe, expect, test } from 'vitest'
import { applyMemorySave } from './memorySave'
import type { ChatMessage } from './useChatStream'

const base: ChatMessage[] = [
  { id: 'm1', role: 'assistant', content: 'Здравствуй', streaming: false },
  { id: 'm2', role: 'user', content: 'Привет', streaming: false },
]

describe('applyMemorySave', () => {
  test('attaches facts to the matching message', () => {
    const next = applyMemorySave(base, {
      chat_id: 'c1',
      message_id: 'm1',
      facts: [{ content: 'Любит чай', category: 'preference' }],
    })
    expect(next.find((m) => m.id === 'm1')?.memorySaves).toEqual([
      { content: 'Любит чай', category: 'preference' },
    ])
    // other messages untouched
    expect(next.find((m) => m.id === 'm2')?.memorySaves).toBeUndefined()
  })

  test('is a no-op when the message is not present', () => {
    const next = applyMemorySave(base, { chat_id: 'c1', message_id: 'gone', facts: [] })
    expect(next).toEqual(base)
  })
})
