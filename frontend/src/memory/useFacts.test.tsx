import { renderHook, waitFor, act } from '@testing-library/react'
import { server, http, HttpResponse } from '../test/msw'
import { AuthProvider } from '../auth/AuthContext'
import { useFacts } from './useFacts'

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <AuthProvider>{children}</AuthProvider>
)

beforeEach(() =>
  localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'r' })),
)

const fact = {
  id: '1',
  category: 'personal',
  content: 'Любит чай',
  source: 'manual',
  created_at: '2026-07-05T10:00:00Z',
  updated_at: '2026-07-05T10:00:00Z',
}

test('loads facts and settings on mount', async () => {
  server.use(
    http.get('/api/memory/facts', () => HttpResponse.json([fact])),
    http.get('/api/memory/settings', () => HttpResponse.json({ auto_capture: true })),
  )
  const { result } = renderHook(() => useFacts(), { wrapper })
  await waitFor(() => expect(result.current.loading).toBe(false))
  expect(result.current.facts[0].content).toBe('Любит чай')
  expect(result.current.autoCapture).toBe(true)
})

test('optimistically edits a fact and rolls back on failure', async () => {
  server.use(
    http.get('/api/memory/facts', () => HttpResponse.json([fact])),
    http.get('/api/memory/settings', () => HttpResponse.json({ auto_capture: true })),
    http.patch('/api/memory/facts/1', () => new HttpResponse(null, { status: 500 })),
  )
  const { result } = renderHook(() => useFacts(), { wrapper })
  await waitFor(() => expect(result.current.loading).toBe(false))

  await act(async () => {
    await result.current.editFact('1', { content: 'Обожает чай' })
  })
  // Reconciled back to the server's value after the failed PATCH.
  expect(result.current.facts[0].content).toBe('Любит чай')
})
