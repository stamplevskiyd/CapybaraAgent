import { render, screen, waitFor, waitForElementToBeRemoved } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, http, HttpResponse } from '../test/msw'
import { AuthProvider } from '../auth/AuthContext'
import { ChatScreen } from './ChatScreen'

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

beforeEach(() =>
  localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'roman' })),
)

test('welcome greets the user and streams a reply after sending', async () => {
  localStorage.setItem('capybara.lastModel', 'llama3.1:8b')
  const chat = { id: 'c1', title: 'Новый чат', model: 'llama3.1:8b', is_favorite: false, created_at: '', updated_at: '' }
  server.use(
    http.get('/api/models', () =>
      HttpResponse.json({ provider: 'ollama', models: ['llama3.1:8b'] }),
    ),
    http.get('/api/chats', () => HttpResponse.json([])),
    http.post('/api/chats', () => HttpResponse.json(chat, { status: 201 })),
    http.post('/api/chats/c1/messages', () =>
      new HttpResponse(
        'event: delta\ndata: {"text":"Здравствуйте"}\n\nevent: done\ndata: {"message_id":"m1"}\n\n',
        {
          headers: { 'Content-Type': 'text/event-stream' },
        },
      ),
    ),
  )
  render(
    <AuthProvider>
      <ChatScreen />
    </AuthProvider>,
  )
  expect(await screen.findByText(/Чем помочь, roman/)).toBeInTheDocument()
  await userEvent.type(screen.getByRole('textbox'), 'Привет{Enter}')
  expect(await screen.findByText('Здравствуйте')).toBeInTheDocument()
})

test('composer lists fetched models and blocks send until a model is valid', async () => {
  localStorage.removeItem('capybara.lastModel')
  server.use(
    http.get('/api/models', () =>
      HttpResponse.json({ provider: 'ollama', models: ['llama3.1:8b'] }),
    ),
    http.get('/api/chats', () => HttpResponse.json([])),
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
  let postChatsCallCount = 0
  server.use(
    http.get('/api/models', () =>
      HttpResponse.json({ provider: 'ollama', models: ['llama3.1:8b'] }),
    ),
    http.get('/api/chats', () => HttpResponse.json([])),
    http.post('/api/chats', () => {
      postChatsCallCount++
      return HttpResponse.json(
        { id: 'c1', title: 'Новый чат', model: 'llama3.1:8b', is_favorite: false, created_at: '', updated_at: '' },
        { status: 201 },
      )
    }),
  )
  render(
    <AuthProvider>
      <ChatScreen />
    </AuthProvider>,
  )
  await screen.findByText(/Чем помочь/)
  // Type text and press Enter WITHOUT selecting a model first (draftModel is null)
  await userEvent.type(screen.getByRole('textbox'), 'Привет{Enter}')
  // Allow any async operations (network requests) a moment to settle
  await new Promise<void>((r) => setTimeout(r, 100))
  // Send must be blocked: no chat was created
  expect(postChatsCallCount).toBe(0)
  // Welcome screen must still be visible — activeChatId was not set
  expect(screen.getByText(/Чем помочь/)).toBeInTheDocument()
})

test('a failed favorite toggle is rolled back to the server state', async () => {
  const chat = {
    id: 'c1',
    title: 'Мой чат',
    model: 'llama3.1:8b',
    is_favorite: false,
    created_at: new Date().toISOString(),
    updated_at: '',
  }
  let patchCalls = 0
  server.use(
    http.get('/api/models', () => HttpResponse.json({ provider: 'ollama', models: ['llama3.1:8b'] })),
    http.get('/api/chats', () => HttpResponse.json([chat])),
    http.patch('/api/chats/c1', () => {
      patchCalls++
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
  // The PATCH was attempted...
  await waitFor(() => expect(patchCalls).toBe(1))
  // ...and because it failed, the optimistic flip is reverted (star shows "add" again).
  await waitFor(() => expect(screen.getByLabelText('В избранное')).toBeInTheDocument())
})

test('shows a loading indicator while chat history is being fetched', async () => {
  const chat = {
    id: 'c2',
    title: 'Мой чат',
    model: 'llama3.1:8b',
    is_favorite: false,
    created_at: new Date().toISOString(),
    updated_at: '',
  }

  let resolveChat!: () => void
  const chatDelay = new Promise<void>((r) => {
    resolveChat = r
  })

  server.use(
    http.get('/api/models', () =>
      HttpResponse.json({ provider: 'ollama', models: ['llama3.1:8b'] }),
    ),
    http.get('/api/chats', () => HttpResponse.json([chat])),
    http.get('/api/chats/:id', async () => {
      await chatDelay
      return HttpResponse.json({ ...chat, messages: [] })
    }),
  )

  render(
    <AuthProvider>
      <ChatScreen />
    </AuthProvider>,
  )

  // Wait for the sidebar chat item to appear, then click to select the chat
  await userEvent.click(await screen.findByText('Мой чат'))

  // Loading indicator should appear while history is being fetched
  expect(await screen.findByRole('status')).toBeInTheDocument()

  // Resolve the delayed response so history loading completes
  resolveChat()

  // Loading indicator should disappear once the request settles
  await waitForElementToBeRemoved(() => screen.queryByRole('status'))
})
