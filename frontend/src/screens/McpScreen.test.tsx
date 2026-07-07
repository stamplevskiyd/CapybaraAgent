import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, http, HttpResponse } from '../test/msw'
import { AuthProvider } from '../auth/AuthContext'
import { McpScreen } from './McpScreen'

beforeEach(() =>
  localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'r' })),
)

const srv = {
  id: 's1',
  name: 'github',
  url: 'https://mcp.example/github',
  enabled: true,
  last_connected_at: '2026-07-07T10:00:00Z',
  last_error: null,
  created_at: '2026-07-07T10:00:00Z',
  updated_at: '2026-07-07T10:00:00Z',
  tools: [{ id: 't1', name: 'search', description: null, enabled: true }],
}

function renderScreen() {
  return render(
    <AuthProvider>
      <McpScreen />
    </AuthProvider>,
  )
}

test('shows the empty state when there are no servers', async () => {
  server.use(http.get('/api/mcp/servers', () => HttpResponse.json([])))
  renderScreen()
  expect(await screen.findByText(/Пока нет подключённых серверов/)).toBeInTheDocument()
})

test('lists servers and opens the connect wizard', async () => {
  server.use(http.get('/api/mcp/servers', () => HttpResponse.json([srv])))
  renderScreen()
  expect(await screen.findByText('github')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Подключить' }))
  expect(screen.getByText('Подключение MCP-сервера')).toBeInTheDocument()
})
