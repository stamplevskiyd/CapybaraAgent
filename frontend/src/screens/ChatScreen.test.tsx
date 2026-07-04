import { render, screen, waitForElementToBeRemoved } from '@testing-library/react'
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
  const chat = { id: 'c1', title: 'Новый чат', model: 'llama3.1:8b', created_at: '', updated_at: '' }
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

test('shows a loading indicator while chat history is being fetched', async () => {
  const chat = {
    id: 'c2',
    title: 'Мой чат',
    model: 'llama3.1:8b',
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
