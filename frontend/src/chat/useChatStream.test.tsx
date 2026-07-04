import { renderHook, act, waitFor } from '@testing-library/react'
import { server, http, HttpResponse } from '../test/msw'
import { AuthProvider } from '../auth/AuthContext'
import { useChatStream } from './useChatStream'

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <AuthProvider>{children}</AuthProvider>
)
beforeEach(() =>
  localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'r' })),
)

test('streams assistant deltas into a message', async () => {
  server.use(
    http.post('/api/chats/c1/messages', () => {
      const body =
        'event: delta\ndata: {"text":"Привет"}\n\n' +
        'event: delta\ndata: {"text":", Роман"}\n\n' +
        'event: done\ndata: {"message_id":"m9"}\n\n'
      return new HttpResponse(body, {
        headers: { 'Content-Type': 'text/event-stream' },
      })
    }),
  )
  const { result } = renderHook(() => useChatStream('c1'), { wrapper })
  await act(async () => {
    await result.current.send('Привет')
  })
  await waitFor(() => expect(result.current.sending).toBe(false))
  const assistant = result.current.messages.find((m) => m.role === 'assistant')!
  expect(assistant.content).toBe('Привет, Роман')
  expect(assistant.streaming).toBe(false)
})

test('a pre-stream error does not leave the assistant bubble streaming', async () => {
  server.use(
    http.post('/api/chats/c1/messages', () => new HttpResponse('gone', { status: 404 })),
  )
  const { result } = renderHook(() => useChatStream('c1'), { wrapper })
  await act(async () => {
    await result.current.send('Привет')
  })
  await waitFor(() => expect(result.current.sending).toBe(false))
  const assistant = result.current.messages.find((m) => m.role === 'assistant')!
  expect(assistant.streaming).toBe(false)
  expect(assistant.error).toBe(true)
})

test('cancel stops an in-flight stream and settles the message', async () => {
  server.use(
    http.post('/api/chats/c1/messages', () => {
      const stream = new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode('event: delta\ndata: {"text":"partial"}\n\n'))
          // never closes; cancel() must abort it
        },
      })
      return new HttpResponse(stream, { headers: { 'Content-Type': 'text/event-stream' } })
    }),
  )
  const { result } = renderHook(() => useChatStream('c1'), { wrapper })
  act(() => { void result.current.send('Привет') })
  await waitFor(() => expect(result.current.messages.some((m) => m.content === 'partial')).toBe(true))
  act(() => { result.current.cancel() })
  await waitFor(() => expect(result.current.sending).toBe(false))
  const assistant = result.current.messages.find((m) => m.role === 'assistant')!
  expect(assistant.streaming).toBe(false)
})

test('regenerate re-sends the last user message', async () => {
  let calls = 0
  server.use(
    http.post('/api/chats/c1/messages', async ({ request }) => {
      calls++
      const { content } = (await request.json()) as { content: string }
      return new HttpResponse(
        `event: delta\ndata: {"text":"${content}!"}\n\nevent: done\ndata: {"message_id":"m${calls}"}\n\n`,
        { headers: { 'Content-Type': 'text/event-stream' } },
      )
    }),
  )
  const { result } = renderHook(() => useChatStream('c1'), { wrapper })
  await act(async () => { await result.current.send('Привет') })
  await act(async () => { await result.current.regenerate() })
  expect(calls).toBe(2)
  const assistants = result.current.messages.filter((m) => m.role === 'assistant')
  expect(assistants.at(-1)!.content).toBe('Привет!')
})
