import { act, renderHook, waitFor } from '@testing-library/react'
import { server, http, HttpResponse } from '../test/msw'
import { AuthProvider, useAuth } from './AuthContext'

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <AuthProvider>{children}</AuthProvider>
)

beforeEach(() => localStorage.clear())

test('login stores token and hydrates display name from /users/me', async () => {
  server.use(
    http.post('/api/auth/login', () =>
      HttpResponse.json({ access_token: 'jwt123', token_type: 'bearer' }),
    ),
    http.get('/api/users/me', () =>
      HttpResponse.json({
        id: 'u1',
        username: 'roman',
        display_name: 'Роман',
        created_at: '',
      }),
    ),
  )
  const { result } = renderHook(() => useAuth(), { wrapper })
  await act(() => result.current.login('roman', 'password1'))
  await waitFor(() => expect(result.current.token).toBe('jwt123'))
  expect(result.current.user?.username).toBe('roman')
  expect(result.current.user?.displayName).toBe('Роман')
  const stored = JSON.parse(localStorage.getItem('capybara.session')!)
  expect(stored.token).toBe('jwt123')
  expect(stored.displayName).toBe('Роман')
})

test('logout clears session', async () => {
  localStorage.setItem(
    'capybara.session',
    JSON.stringify({ token: 'x', username: 'roman' }),
  )
  const { result } = renderHook(() => useAuth(), { wrapper })
  expect(result.current.token).toBe('x')
  act(() => result.current.logout())
  expect(result.current.token).toBeNull()
  expect(localStorage.getItem('capybara.session')).toBeNull()
})
