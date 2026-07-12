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

test('put sends a JSON body with the auth header', async () => {
  let seenBody: unknown = null
  server.use(
    http.put('/api/chat-settings/t1', async ({ request }) => {
      expect(request.headers.get('Authorization')).toBe('Bearer t0ken')
      seenBody = await request.json()
      return HttpResponse.json({ thread_id: 't1', is_favorite: true, model: null })
    }),
  )
  const client = createApiClient({ getToken: () => 't0ken', onUnauthorized: () => {} })
  const pref = await client.put<{ thread_id: string }>('/chat-settings/t1', {
    is_favorite: true,
    model: null,
  })
  expect(pref.thread_id).toBe('t1')
  expect(seenBody).toEqual({ is_favorite: true, model: null })
})
