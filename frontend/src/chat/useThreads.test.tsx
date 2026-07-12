import { renderHook, waitFor } from '@testing-library/react'
import { server, http, HttpResponse } from '../test/msw'
import { AuthProvider } from '../auth/AuthContext'
import { useThreads } from './useThreads'

vi.mock('../chainlit/client', () => ({
  chainlitClient: {
    listThreads: async () => ({
      pageInfo: { hasNextPage: false, startCursor: null, endCursor: null },
      data: [{ id: 't1', name: 'Чат', createdAt: '2026-07-11T00:00:00Z', steps: [] }],
    }),
  },
}))

const wrapper = ({ children }: { children: React.ReactNode }) => <AuthProvider>{children}</AuthProvider>

beforeEach(() =>
  localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'r' })),
)

test('merges the mode from chat-settings into the thread entry', async () => {
  server.use(
    http.get('/api/chat-settings', () =>
      HttpResponse.json([{ thread_id: 't1', is_favorite: false, model: 'qwen2.5', mode: 'smart' }]),
    ),
  )
  const { result } = renderHook(() => useThreads(), { wrapper })
  await waitFor(() => expect(result.current.chats.length).toBe(1))
  expect(result.current.chats[0].mode).toBe('smart')
})

test('defaults mode to fast when no pref exists', async () => {
  const { result } = renderHook(() => useThreads(), { wrapper })
  await waitFor(() => expect(result.current.chats.length).toBe(1))
  expect(result.current.chats[0].mode).toBe('fast')
})
