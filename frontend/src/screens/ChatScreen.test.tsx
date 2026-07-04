import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, http, HttpResponse } from '../test/msw'
import { AuthProvider } from '../auth/AuthContext'
import { ChatScreen } from './ChatScreen'

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
  expect(sendBtn).not.toBeDisabled()
})
