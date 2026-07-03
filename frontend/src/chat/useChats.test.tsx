import { renderHook, waitFor, act } from '@testing-library/react'
import { server, http, HttpResponse } from '../test/msw'
import { AuthProvider } from '../auth/AuthContext'
import { useChats } from './useChats'

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <AuthProvider>{children}</AuthProvider>
)
beforeEach(() =>
  localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'r' })),
)

test('loads chats on mount and creates a new one', async () => {
  const chat = { id: '1', title: 'Новый чат', created_at: '', updated_at: '' }
  server.use(
    http.get('/api/chats', () => HttpResponse.json([])),
    http.post('/api/chats', () => HttpResponse.json(chat, { status: 201 })),
  )
  const { result } = renderHook(() => useChats(), { wrapper })
  await waitFor(() => expect(result.current.loading).toBe(false))
  expect(result.current.chats).toEqual([])
  await act(async () => {
    await result.current.newChat()
  })
  expect(result.current.chats[0].id).toBe('1')
})
