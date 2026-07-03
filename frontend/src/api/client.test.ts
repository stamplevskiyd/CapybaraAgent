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
