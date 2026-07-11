import type { IStep } from '@chainlit/react-client'
import { convertChainlitMessages } from './convertChainlitMessage'

const at = '2026-07-11T00:00:00Z'

test('flattens messages nested under a run step (live/resume shape)', () => {
  const steps: IStep[] = [
    { id: 'u1', name: 'user', type: 'user_message', output: 'Привет', createdAt: at },
    {
      id: 'r1',
      name: 'on_message',
      type: 'run',
      output: '',
      createdAt: at,
      steps: [
        { id: 'a1', name: 'Assistant', type: 'assistant_message', output: 'Здравствуйте', createdAt: at },
      ],
    },
  ]

  const messages = convertChainlitMessages(steps)

  expect(messages).toEqual([
    { id: 'u1', role: 'user', content: 'Привет', streaming: false, error: undefined },
    { id: 'a1', role: 'assistant', content: 'Здравствуйте', streaming: false, error: undefined },
  ])
})

test('attaches sibling tool steps inside a run to its assistant message', () => {
  const steps: IStep[] = [
    { id: 'u1', name: 'user', type: 'user_message', output: 'Что ты помнишь?', createdAt: at },
    {
      id: 'r1',
      name: 'on_message',
      type: 'run',
      output: '',
      createdAt: at,
      steps: [
        { id: 't1', name: 'recall', type: 'tool', input: '{"query":"x"}', output: 'facts', createdAt: at },
        { id: 'a1', name: 'Assistant', type: 'assistant_message', output: 'Вот что помню', createdAt: at },
      ],
    },
  ]

  const assistant = convertChainlitMessages(steps)[1]

  expect(assistant.content).toBe('Вот что помню')
  expect(assistant.toolCalls).toEqual([
    { id: 't1', name: 'recall', args: { query: 'x' }, result: 'facts', running: false },
  ])
})

test('a running tool before the first token shows as a streaming placeholder', () => {
  const steps: IStep[] = [
    { id: 'u1', name: 'user', type: 'user_message', output: 'hi', createdAt: at },
    {
      id: 'r1',
      name: 'on_message',
      type: 'run',
      output: '',
      createdAt: at,
      steps: [
        { id: 't1', name: 'recall', type: 'tool', input: '', output: '', streaming: true, createdAt: at },
      ],
    },
  ]

  const messages = convertChainlitMessages(steps)

  expect(messages[1].role).toBe('assistant')
  expect(messages[1].streaming).toBe(true)
  expect(messages[1].toolCalls?.[0]).toMatchObject({ name: 'recall', running: true })
})

test('error messages surface with the error flag', () => {
  const steps: IStep[] = [
    {
      id: 'r1',
      name: 'on_message',
      type: 'run',
      output: '',
      createdAt: at,
      steps: [
        { id: 'e1', name: 'Error', type: 'assistant_message', output: 'Не смог', isError: true, createdAt: at },
      ],
    },
  ]

  const [message] = convertChainlitMessages(steps)

  expect(message).toMatchObject({ role: 'assistant', content: 'Не смог', error: true })
})

test('top-level flat messages still convert (no run wrapper)', () => {
  const steps: IStep[] = [
    { id: 'u1', name: 'user', type: 'user_message', output: 'Hello', createdAt: at },
    { id: 'x1', name: 'internal', type: 'tool', output: 'hidden', createdAt: at },
    { id: 'a1', name: 'Assistant', type: 'assistant_message', output: 'Hi', createdAt: at },
  ]

  const messages = convertChainlitMessages(steps)

  expect(messages.map((m) => m.id)).toEqual(['u1', 'a1'])
  // the stray tool attaches to the following assistant message
  expect(messages[1].toolCalls?.[0].name).toBe('internal')
})
