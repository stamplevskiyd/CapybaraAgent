import { describe, expect, test } from 'vitest'
import { convertChainlitMessage } from './convertChainlitMessage'

describe('convertChainlitMessage', () => {
  test('maps user and assistant messages to the current UI shape', () => {
    expect(
      convertChainlitMessage({
        id: 'u1',
        name: 'User',
        type: 'user_message',
        output: 'Hello',
        createdAt: '2026-07-08T00:00:00Z',
      }),
    ).toMatchObject({ id: 'u1', role: 'user', content: 'Hello', streaming: false })

    expect(
      convertChainlitMessage({
        id: 'a1',
        name: 'Assistant',
        type: 'assistant_message',
        output: 'Hi',
        createdAt: '2026-07-08T00:00:00Z',
      }),
    ).toMatchObject({ id: 'a1', role: 'assistant', content: 'Hi', streaming: false })
  })

  test('maps child tool steps to existing tool call state', () => {
    expect(
      convertChainlitMessage({
        id: 'a2',
        name: 'Assistant',
        type: 'assistant_message',
        output: 'Done',
        createdAt: '2026-07-08T00:00:00Z',
        steps: [
          {
            id: 'tool-1',
            name: 'recall_memory',
            type: 'tool',
            input: '{"query":"project"}',
            output: 'Found 2 facts',
            createdAt: '2026-07-08T00:00:00Z',
          },
        ],
      }),
    ).toMatchObject({
      toolCalls: [
        {
          id: 'tool-1',
          name: 'recall_memory',
          args: { query: 'project' },
          result: 'Found 2 facts',
          running: false,
        },
      ],
    })
  })
})
