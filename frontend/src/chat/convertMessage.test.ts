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
  const streaming: ChatMessage = {
    id: 'm2',
    role: 'assistant',
    content: 'partial',
    streaming: true,
  }
  const done: ChatMessage = { id: 'm3', role: 'assistant', content: 'full', streaming: false }
  expect(convertMessage(streaming).status?.type).toBe('running')
  expect(convertMessage(done).status).toBeUndefined()
})

test('emits tool-call parts before the text part', () => {
  const msg = convertMessage({
    id: 'a1',
    role: 'assistant',
    content: 'Ответ',
    streaming: false,
    toolCalls: [
      { id: 't1', name: 'recall', args: { query: 'х' }, result: 'r', running: false },
    ],
  })
  expect(msg.content).toHaveLength(2)
  expect(msg.content[0]).toMatchObject({
    type: 'tool-call',
    toolCallId: 't1',
    toolName: 'recall',
    args: { query: 'х' },
    result: 'r',
  })
  expect(msg.content[1]).toMatchObject({ type: 'text', text: 'Ответ' })
})

test('a running tool call has no result', () => {
  const msg = convertMessage({
    id: 'a2',
    role: 'assistant',
    content: '',
    streaming: true,
    toolCalls: [{ id: 't2', name: 'recall', args: {}, running: true }],
  })
  expect(msg.content[0]).toMatchObject({ type: 'tool-call', toolCallId: 't2' })
  expect((msg.content[0] as { result?: unknown }).result).toBeUndefined()
})

test('passes memorySaves through message metadata', () => {
  const msg = convertMessage({
    id: 'a1',
    role: 'assistant',
    content: 'Ответ',
    streaming: false,
    memorySaves: [{ content: 'Любит чай', category: 'preference' }],
  })
  expect((msg.metadata?.custom as { memorySaves?: unknown })?.memorySaves).toEqual([
    { content: 'Любит чай', category: 'preference' },
  ])
})
