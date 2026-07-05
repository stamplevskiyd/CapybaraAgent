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
  expect(assistant.error).toBeFalsy()
})

test('switching to another chat aborts the in-flight stream', async () => {
  server.use(
    http.post('/api/chats/c1/messages', () => {
      const stream = new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode('event: delta\ndata: {"text":"partial"}\n\n'))
          // never closes; navigating away must abort it
        },
      })
      return new HttpResponse(stream, { headers: { 'Content-Type': 'text/event-stream' } })
    }),
  )
  const { result, rerender } = renderHook(({ id }) => useChatStream(id), {
    wrapper,
    initialProps: { id: 'c1' as string | null },
  })
  act(() => {
    void result.current.send('Привет')
  })
  await waitFor(() => expect(result.current.sending).toBe(true))
  // Navigate to a different chat while the stream is still open.
  rerender({ id: 'c2' })
  // The stream for c1 must be aborted so the composer is freed.
  await waitFor(() => expect(result.current.sending).toBe(false))
})

test('invokes onTitle when a title event arrives', async () => {
  const onTitle = vi.fn()
  server.use(
    http.post('/api/chats/c1/messages', () => {
      const body =
        'event: delta\ndata: {"text":"Хай"}\n\n' +
        'event: done\ndata: {"message_id":"m1"}\n\n' +
        'event: title\ndata: {"title":"Про капибар"}\n\n'
      return new HttpResponse(body, { headers: { 'Content-Type': 'text/event-stream' } })
    }),
  )
  const { result } = renderHook(() => useChatStream('c1', onTitle), { wrapper })
  await act(async () => {
    await result.current.send('Привет')
  })
  await waitFor(() => expect(result.current.sending).toBe(false))
  expect(onTitle).toHaveBeenCalledWith('Про капибар')
})

test('sending clears on done even when a title frame trails it', async () => {
  let ctrl!: ReadableStreamDefaultController
  const stream = new ReadableStream({
    start(controller) {
      ctrl = controller
      controller.enqueue(new TextEncoder().encode('event: delta\ndata: {"text":"Хай"}\n\n'))
      controller.enqueue(new TextEncoder().encode('event: done\ndata: {"message_id":"m1"}\n\n'))
    },
  })
  server.use(
    http.post('/api/chats/c1/messages', () =>
      new HttpResponse(stream, { headers: { 'Content-Type': 'text/event-stream' } }),
    ),
  )
  const onTitle = vi.fn()
  const { result } = renderHook(() => useChatStream('c1', onTitle), { wrapper })
  act(() => {
    void result.current.send('Привет')
  })
  // After delta+done are consumed, the composer is freed even though the stream is still open.
  await waitFor(() => expect(result.current.sending).toBe(false))
  // Now the trailing title arrives and the stream closes.
  await act(async () => {
    ctrl.enqueue(new TextEncoder().encode('event: title\ndata: {"title":"Про капибар"}\n\n'))
    ctrl.close()
  })
  await waitFor(() => expect(onTitle).toHaveBeenCalledWith('Про капибар'))
})

test('regenerate calls /messages/regenerate and replaces the last assistant without duplicating the user bubble', async () => {
  let regenerateCalled = false

  server.use(
    http.post('/api/chats/c1/messages', () =>
      new HttpResponse(
        'event: delta\ndata: {"text":"Первый ответ"}\n\nevent: done\ndata: {"message_id":"m1"}\n\n',
        { headers: { 'Content-Type': 'text/event-stream' } },
      ),
    ),
    http.post('/api/chats/c1/messages/regenerate', () => {
      regenerateCalled = true
      return new HttpResponse(
        'event: delta\ndata: {"text":"Другой ответ"}\n\nevent: done\ndata: {"message_id":"m2"}\n\n',
        { headers: { 'Content-Type': 'text/event-stream' } },
      )
    }),
  )

  const { result } = renderHook(() => useChatStream('c1'), { wrapper })

  // Seed: send a message so state has one user + one assistant message.
  await act(async () => { await result.current.send('Привет') })
  await waitFor(() => expect(result.current.sending).toBe(false))

  const usersBefore = result.current.messages.filter((m) => m.role === 'user').length

  // Regenerate: should hit the new endpoint, not re-append a user bubble.
  await act(async () => { await result.current.regenerate() })
  await waitFor(() => expect(result.current.sending).toBe(false))

  // (a) The regenerate endpoint was hit.
  expect(regenerateCalled).toBe(true)
  // (b) User bubble count is unchanged — no duplicate.
  expect(result.current.messages.filter((m) => m.role === 'user').length).toBe(usersBefore)
  // (c) Last assistant message contains the regenerated text.
  const lastAssistant = result.current.messages.filter((m) => m.role === 'assistant').at(-1)!
  expect(lastAssistant.content).toBe('Другой ответ')
  // (d) Sending is settled.
  expect(result.current.sending).toBe(false)
})
