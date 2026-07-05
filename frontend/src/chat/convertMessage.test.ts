import { convertMessage } from './convertMessage'
import type { ChatMessage } from './useChatStream'

test('wraps text content into a single text part', () => {
  const msg: ChatMessage = { id: 'm1', role: 'assistant', content: 'Привет', streaming: false }
  const out = convertMessage(msg)
  expect(out.role).toBe('assistant')
  expect(out.id).toBe('m1')
  expect(out.content).toEqual([{ type: 'text', text: 'Привет' }])
})

test('emits no parts for empty content (typing-indicator placeholder)', () => {
  const empty: ChatMessage = { id: 'm4', role: 'assistant', content: '', streaming: true }
  const out = convertMessage(empty)
  expect(out.content).toEqual([])
  expect(out.status?.type).toBe('running')
})

test('marks a streaming message as running, settled otherwise', () => {
  const streaming: ChatMessage = { id: 'm2', role: 'assistant', content: 'partial', streaming: true }
  const done: ChatMessage = { id: 'm3', role: 'assistant', content: 'full', streaming: false }
  expect(convertMessage(streaming).status?.type).toBe('running')
  expect(convertMessage(done).status).toBeUndefined()
})
