import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, http, HttpResponse } from '../test/msw'
import { AuthProvider } from '../auth/AuthContext'
import { ChatScreen } from './ChatScreen'

const sent = vi.hoisted(() => ({ calls: [] as { content: string; model?: string | null; mode?: string }[] }))
const openThreadSpy = vi.hoisted(() => vi.fn())
const conn = vi.hoisted(() => ({ value: true }))

vi.mock('../chainlit/useChainlitThread', async () => {
  const React = await vi.importActual<typeof import('react')>('react')
  type Message = {
    id: string
    role: 'user' | 'assistant'
    content: string
    streaming: boolean
  }
  let nextId = 0

  return {
    useChainlitThread: () => {
      const [messages, setMessages] = React.useState<Message[]>([])
      const send = React.useCallback(async (content: string, model?: string | null, mode?: string) => {
        sent.calls.push({ content, model, mode })
        setMessages((prev) => [
          ...prev,
          { id: `user-${nextId++}`, role: 'user', content, streaming: false },
          {
            id: `assistant-${nextId++}`,
            role: 'assistant',
            content: 'Здравствуйте',
            streaming: false,
          },
        ])
      }, [])

      return {
        messages,
        threadId: messages.length > 0 ? 'th-new' : undefined,
        connected: conn.value,
        sending: false,
        send,
        openThread: openThreadSpy,
        newThread: React.useCallback(() => setMessages([]), []),
        cancel: () => {},
      }
    },
  }
})

// ThreadPrimitive.Viewport uses ResizeObserver and scrollTo for autoscroll detection;
// jsdom does not provide these, so install no-op stubs.
beforeAll(() => {
  if (typeof globalThis.ResizeObserver === 'undefined') {
    globalThis.ResizeObserver = class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  }
  if (typeof HTMLElement.prototype.scrollTo === 'undefined') {
    HTMLElement.prototype.scrollTo = () => {}
  }
})

beforeEach(() => {
  localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'roman' }))
  sent.calls = []
  conn.value = true
  openThreadSpy.mockReset()
})

/** One persisted Chainlit thread as the list endpoint returns it. */
const thread = {
  id: 'c1',
  name: 'Мой чат',
  createdAt: '2026-07-10T10:00:00Z',
  steps: [],
}

test('welcome greets the user and streams a reply after sending', async () => {
  localStorage.setItem('capybara.lastModel', 'llama3.1:8b')
  let prefPut: { id: string; body: unknown } | null = null
  server.use(
    http.get('/api/models', () =>
      HttpResponse.json({ provider: 'ollama', models: ['llama3.1:8b'] }),
    ),
    http.put('/api/chat-prefs/:threadId', async ({ params, request }) => {
      prefPut = { id: String(params.threadId), body: await request.json() }
      return HttpResponse.json({ thread_id: params.threadId, is_favorite: false, model: null })
    }),
  )
  render(
    <AuthProvider>
      <ChatScreen />
    </AuthProvider>,
  )
  expect(await screen.findByText(/Чем помочь, roman/)).toBeInTheDocument()
  await userEvent.type(screen.getByRole('textbox'), 'Привет{Enter}')
  expect(await screen.findByText('Здравствуйте')).toBeInTheDocument()
  // The selected model and mode ride in the message itself — the backend reads them from there.
  expect(sent.calls).toEqual([{ content: 'Привет', model: 'llama3.1:8b', mode: 'fast' }])
  // Adopting the new thread id also persists that model so the thread remembers it.
  await waitFor(() => expect(prefPut).not.toBeNull())
  expect(prefPut).toMatchObject({ id: 'th-new', body: { is_favorite: false, model: 'llama3.1:8b' } })
})

test('composer lists fetched models and blocks send until a model is valid', async () => {
  localStorage.removeItem('capybara.lastModel')
  server.use(
    http.get('/api/models', () =>
      HttpResponse.json({ provider: 'ollama', models: ['llama3.1:8b'] }),
    ),
  )
  render(
    <AuthProvider>
      <ChatScreen />
    </AuthProvider>,
  )
  await screen.findByText(/Чем помочь/)
  const sendBtn = screen.getByLabelText('Отправить')
  expect(sendBtn).toBeDisabled()

  // Wait for models list to populate from the API response
  expect(await screen.findByRole('option', { name: 'llama3.1:8b' })).toBeInTheDocument()

  await userEvent.selectOptions(screen.getByLabelText('Модель'), 'llama3.1:8b')
  await userEvent.type(screen.getByRole('textbox'), 'Привет') // Send also gates on non-empty input
  expect(sendBtn).not.toBeDisabled()
})

test('Enter is blocked when no valid model is selected', async () => {
  localStorage.removeItem('capybara.lastModel')
  server.use(
    http.get('/api/models', () =>
      HttpResponse.json({ provider: 'ollama', models: ['llama3.1:8b'] }),
    ),
  )
  render(
    <AuthProvider>
      <ChatScreen />
    </AuthProvider>,
  )
  await screen.findByText(/Чем помочь/)
  // Type text and press Enter WITHOUT selecting a model first (draftModel is null)
  await userEvent.type(screen.getByRole('textbox'), 'Привет{Enter}')
  // Allow any async operations a moment to settle
  await new Promise<void>((r) => setTimeout(r, 100))
  // Send must be blocked: nothing left the composer
  expect(sent.calls).toEqual([])
  // Welcome screen must still be visible — no thread became active
  expect(screen.getByText(/Чем помочь/)).toBeInTheDocument()
})

test('Enter does not send while the chat transport is not connected', async () => {
  conn.value = false
  localStorage.setItem('capybara.lastModel', 'llama3.1:8b')
  server.use(
    http.get('/api/models', () =>
      HttpResponse.json({ provider: 'ollama', models: ['llama3.1:8b'] }),
    ),
  )
  render(
    <AuthProvider>
      <ChatScreen />
    </AuthProvider>,
  )
  await screen.findByText(/Чем помочь/)
  // A valid model is selected, but the socket is not connected: pressing Enter must not
  // emit — otherwise the message is dropped into a not-yet-ready socket and lost.
  await userEvent.type(screen.getByRole('textbox'), 'Привет{Enter}')
  await new Promise<void>((r) => setTimeout(r, 100))
  expect(sent.calls).toEqual([])
})

test('a failed favorite toggle is rolled back to the server state', async () => {
  let putCalls = 0
  server.use(
    http.get('/api/models', () =>
      HttpResponse.json({ provider: 'ollama', models: ['llama3.1:8b'] }),
    ),
    http.post('/chainlit/project/threads', () =>
      HttpResponse.json({
        pageInfo: { hasNextPage: false, startCursor: null, endCursor: null },
        data: [thread],
      }),
    ),
    http.put('/api/chat-prefs/c1', () => {
      putCalls++
      return new HttpResponse('boom', { status: 500 })
    }),
  )
  render(
    <AuthProvider>
      <ChatScreen />
    </AuthProvider>,
  )
  const star = await screen.findByLabelText('В избранное')
  await userEvent.click(star)
  // The PUT was attempted...
  await waitFor(() => expect(putCalls).toBe(1))
  // ...and because it failed, the optimistic flip is reverted (star shows "add" again).
  await waitFor(() => expect(screen.getByLabelText('В избранное')).toBeInTheDocument())
})

test('selecting a thread resumes it through the Chainlit session', async () => {
  server.use(
    http.get('/api/models', () =>
      HttpResponse.json({ provider: 'ollama', models: ['llama3.1:8b'] }),
    ),
    http.post('/chainlit/project/threads', () =>
      HttpResponse.json({
        pageInfo: { hasNextPage: false, startCursor: null, endCursor: null },
        data: [thread],
      }),
    ),
  )
  render(
    <AuthProvider>
      <ChatScreen />
    </AuthProvider>,
  )

  await userEvent.click(await screen.findByText('Мой чат'))

  expect(openThreadSpy).toHaveBeenCalledWith('c1')
  // The thread header shows the selected thread's title.
  expect(screen.getAllByText('Мой чат').length).toBeGreaterThan(1)
})

test('selecting a model on an active thread persists it to chat-prefs', async () => {
  let putBody: unknown = null
  server.use(
    http.get('/api/models', () =>
      HttpResponse.json({ provider: 'ollama', models: ['llama3.1:8b', 'qwen3:8b'] }),
    ),
    http.post('/chainlit/project/threads', () =>
      HttpResponse.json({
        pageInfo: { hasNextPage: false, startCursor: null, endCursor: null },
        data: [thread],
      }),
    ),
    http.put('/api/chat-prefs/c1', async ({ request }) => {
      putBody = await request.json()
      return HttpResponse.json({ thread_id: 'c1', is_favorite: false, model: 'qwen3:8b' })
    }),
  )
  render(
    <AuthProvider>
      <ChatScreen />
    </AuthProvider>,
  )

  await userEvent.click(await screen.findByText('Мой чат'))
  await userEvent.selectOptions(await screen.findByLabelText('Модель'), 'qwen3:8b')

  await waitFor(() => expect(putBody).toMatchObject({ is_favorite: false, model: 'qwen3:8b' }))
})

test('selecting a mode on an active thread persists it to chat-prefs', async () => {
  let putBody: unknown = null
  server.use(
    http.get('/api/models', () =>
      HttpResponse.json({ provider: 'ollama', models: ['llama3.1:8b'] }),
    ),
    http.post('/chainlit/project/threads', () =>
      HttpResponse.json({
        pageInfo: { hasNextPage: false, startCursor: null, endCursor: null },
        data: [thread],
      }),
    ),
    http.put('/api/chat-prefs/c1', async ({ request }) => {
      putBody = await request.json()
      return HttpResponse.json({ thread_id: 'c1', is_favorite: false, model: null, mode: 'smart' })
    }),
  )
  render(
    <AuthProvider>
      <ChatScreen />
    </AuthProvider>,
  )
  await userEvent.click(await screen.findByText('Мой чат'))
  await userEvent.selectOptions(await screen.findByLabelText('Режим агента'), 'smart')
  await waitFor(() =>
    expect(putBody).toMatchObject({ mode: 'smart' }),
  )
})

test('the sidebar can be collapsed and expanded via the toggle buttons', async () => {
  localStorage.removeItem('capybara.sidebarCollapsed')
  server.use(
    http.get('/api/models', () => HttpResponse.json({ provider: 'ollama', models: [] })),
  )
  render(
    <AuthProvider>
      <ChatScreen />
    </AuthProvider>,
  )
  await screen.findByText(/Чем помочь/)
  // Expanded: the collapse control is present, the floating expand button is not.
  expect(screen.queryByLabelText('Развернуть панель')).toBeNull()
  await userEvent.click(screen.getByLabelText('Свернуть панель'))
  // Collapsed: the floating expand button appears.
  expect(await screen.findByLabelText('Развернуть панель')).toBeInTheDocument()
  await userEvent.click(screen.getByLabelText('Развернуть панель'))
  expect(screen.queryByLabelText('Развернуть панель')).toBeNull()
})
