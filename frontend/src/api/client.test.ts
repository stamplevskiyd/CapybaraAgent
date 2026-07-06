import { server, http, HttpResponse } from '../test/msw'
import { createApiClient, ApiError } from './client'

test('get attaches bearer token and parses json', async () => {
  server.use(
    http.get('/api/chats', ({ request }) => {
      expect(request.headers.get('Authorization')).toBe('Bearer t0ken')
      return HttpResponse.json([{ id: '1', title: 'Hi' }])
    }),
  )
  const client = createApiClient({ getToken: () => 't0ken', onUnauthorized: () => {} })
  const chats = await client.get<{ id: string }[]>('/chats')
  expect(chats[0].id).toBe('1')
})

test('401 throws ApiError and calls onUnauthorized', async () => {
  server.use(http.get('/api/chats', () => new HttpResponse(null, { status: 401 })))
  const onUnauthorized = vi.fn()
  const client = createApiClient({ getToken: () => null, onUnauthorized })
  await expect(client.get('/chats')).rejects.toBeInstanceOf(ApiError)
  expect(onUnauthorized).toHaveBeenCalledOnce()
})

test('stream throws ApiError on a non-ok pre-stream response', async () => {
  server.use(
    http.post('/api/chats/x/messages', () => new HttpResponse('not found', { status: 404 })),
  )
  const client = createApiClient({ getToken: () => 't0ken', onUnauthorized: () => {} })
  await expect(client.stream('/chats/x/messages', { content: 'hi' })).rejects.toMatchObject({
    name: 'ApiError',
    status: 404,
  })
})

test('stream returns the streaming response when ok', async () => {
  server.use(
    http.post(
      '/api/chats/x/messages',
      () =>
        new HttpResponse('event: done\ndata: {}\n\n', {
          headers: { 'Content-Type': 'text/event-stream' },
        }),
    ),
  )
  const client = createApiClient({ getToken: () => 't0ken', onUnauthorized: () => {} })
  const res = await client.stream('/chats/x/messages', { content: 'hi' })
  expect(res.ok).toBe(true)
  expect(res.body).not.toBeNull()
})

describe('eventStream', () => {
  test('opens a GET stream to the given path with the auth header', async () => {
    let seenMethod = ''
    let seenAuth: string | null = null
    server.use(
      http.get('/api/events', ({ request }) => {
        seenMethod = request.method
        seenAuth = request.headers.get('Authorization')
        return new HttpResponse('event: memory-save\ndata: {}\n\n', {
          headers: { 'Content-Type': 'text/event-stream' },
        })
      }),
    )
    const api = createApiClient({ getToken: () => 'tok', onUnauthorized: () => {} })
    const res = await api.eventStream('/events')
    expect(res.ok).toBe(true)
    expect(seenMethod).toBe('GET')
    expect(seenAuth).toBe('Bearer tok')
  })
})
