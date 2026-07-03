import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, http, HttpResponse } from '../test/msw'
import { AuthProvider } from '../auth/AuthContext'
import { ChatScreen } from './ChatScreen'

beforeEach(() =>
  localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'roman' })),
)

test('welcome greets the user and streams a reply after sending', async () => {
  const chat = { id: 'c1', title: 'Новый чат', created_at: '', updated_at: '' }
  server.use(
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
