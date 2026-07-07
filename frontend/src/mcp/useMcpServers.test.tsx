import { renderHook, waitFor, act } from '@testing-library/react'
import { server, http, HttpResponse } from '../test/msw'
import { AuthProvider } from '../auth/AuthContext'
import { useMcpServers } from './useMcpServers'

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <AuthProvider>{children}</AuthProvider>
)

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

test('loads servers on mount', async () => {
  server.use(http.get('/api/mcp/servers', () => HttpResponse.json([srv])))
  const { result } = renderHook(() => useMcpServers(), { wrapper })
  await waitFor(() => expect(result.current.loading).toBe(false))
  expect(result.current.servers[0].name).toBe('github')
})

test('connect prepends the created server', async () => {
  const created = { ...srv, id: 's2', name: 'fs' }
  server.use(
    http.get('/api/mcp/servers', () => HttpResponse.json([srv])),
    http.post('/api/mcp/servers', () => HttpResponse.json(created, { status: 201 })),
  )
  const { result } = renderHook(() => useMcpServers(), { wrapper })
  await waitFor(() => expect(result.current.loading).toBe(false))
  await act(async () => {
    await result.current.connect('fs', 'https://mcp.example/fs', {})
  })
  expect(result.current.servers[0].id).toBe('s2')
})

test('connect rethrows on failure', async () => {
  server.use(
    http.get('/api/mcp/servers', () => HttpResponse.json([])),
    http.post('/api/mcp/servers', () =>
      HttpResponse.json({ detail: 'unreachable' }, { status: 502 }),
    ),
  )
  const { result } = renderHook(() => useMcpServers(), { wrapper })
  await waitFor(() => expect(result.current.loading).toBe(false))
  await act(async () => {
    await expect(result.current.connect('x', 'https://x', {})).rejects.toBeTruthy()
  })
})

test('toggleServer rolls back on failure', async () => {
  let calls = 0
  server.use(
    http.get('/api/mcp/servers', () => {
      calls += 1
      return HttpResponse.json([srv]) // reload returns enabled:true again
    }),
    http.patch('/api/mcp/servers/s1', () => new HttpResponse(null, { status: 500 })),
  )
  const { result } = renderHook(() => useMcpServers(), { wrapper })
  await waitFor(() => expect(result.current.loading).toBe(false))
  await act(async () => {
    await result.current.toggleServer('s1', false)
  })
  await waitFor(() => expect(result.current.servers[0].enabled).toBe(true))
  expect(calls).toBeGreaterThan(1) // reload happened
})

test('toggleTool flips a tool optimistically', async () => {
  server.use(
    http.get('/api/mcp/servers', () => HttpResponse.json([srv])),
    http.patch('/api/mcp/servers/s1/tools/t1', () =>
      HttpResponse.json({ id: 't1', name: 'search', description: null, enabled: false }),
    ),
  )
  const { result } = renderHook(() => useMcpServers(), { wrapper })
  await waitFor(() => expect(result.current.loading).toBe(false))
  await act(async () => {
    await result.current.toggleTool('s1', 't1', false)
  })
  expect(result.current.servers[0].tools[0].enabled).toBe(false)
})
