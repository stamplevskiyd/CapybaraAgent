import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, http, HttpResponse } from '../test/msw'
import { AuthProvider } from '../auth/AuthContext'
import { ChatScreen } from './ChatScreen'

// This test exercises navigation, not the chat runtime; mock the Chainlit hook so ChatScreen
// renders without a live Recoil/Chainlit session (which it otherwise requires).
vi.mock('../chainlit/useChainlitThread', () => ({
  useChainlitThread: () => ({
    messages: [],
    sending: false,
    loadingHistory: false,
    send: async () => {},
    loadHistory: async () => {},
    cancel: () => {},
    regenerate: async () => {},
  }),
}))

// ThreadPrimitive.Viewport uses ResizeObserver and scrollTo, which jsdom lacks; stub them.
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
  localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'r' })),
)

test('clicking «Память» swaps main to the memory screen and back', async () => {
  server.use(
    http.get('/api/models', () =>
      HttpResponse.json({ provider: 'ollama', models: ['llama3.1:8b'] }),
    ),
    http.get('/api/chats', () => HttpResponse.json([])),
    http.get('/api/memory/facts', () => HttpResponse.json([])),
    http.get('/api/memory/settings', () => HttpResponse.json({ auto_capture: true })),
  )
  render(
    <AuthProvider>
      <ChatScreen />
    </AuthProvider>,
  )

  // Starts on the chat welcome state.
  expect(await screen.findByText(/Чем помочь/)).toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: 'Память' }))
  // Memory screen header appears (heading role disambiguates from the nav button).
  expect(await screen.findByRole('heading', { name: 'Память' })).toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: 'Новый чат' }))
  expect(await screen.findByText(/Чем помочь/)).toBeInTheDocument()
})
