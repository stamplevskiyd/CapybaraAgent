import { server, http, HttpResponse } from '../test/msw'
import { createApiClient } from '../api/client'
import {
  createServer,
  deleteServer,
  listServers,
  refreshServer,
  setServerEnabled,
  setToolEnabled,
} from './mcpApi'

const api = createApiClient({ getToken: () => 't', onUnauthorized: () => {} })

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

test('listServers GETs /mcp/servers', async () => {
  server.use(http.get('/api/mcp/servers', () => HttpResponse.json([srv])))
  expect((await listServers(api))[0].name).toBe('github')
})

test('createServer POSTs name/url/headers', async () => {
  let body: unknown
  server.use(
    http.post('/api/mcp/servers', async ({ request }) => {
      body = await request.json()
      return HttpResponse.json(srv, { status: 201 })
    }),
  )
  await createServer(api, 'github', 'https://mcp.example/github', { Authorization: 'Bearer x' })
  expect(body).toEqual({
    name: 'github',
    url: 'https://mcp.example/github',
    headers: { Authorization: 'Bearer x' },
  })
})

test('setServerEnabled PATCHes enabled', async () => {
  let body: unknown
  server.use(
    http.patch('/api/mcp/servers/s1', async ({ request }) => {
      body = await request.json()
      return HttpResponse.json({ ...srv, enabled: false })
    }),
  )
  await setServerEnabled(api, 's1', false)
  expect(body).toEqual({ enabled: false })
})

test('setToolEnabled PATCHes the tool', async () => {
  server.use(
    http.patch('/api/mcp/servers/s1/tools/t1', () =>
      HttpResponse.json({ id: 't1', name: 'search', description: null, enabled: false }),
    ),
  )
  expect((await setToolEnabled(api, 's1', 't1', false)).enabled).toBe(false)
})

test('refreshServer POSTs /refresh and deleteServer DELETEs', async () => {
  server.use(
    http.post('/api/mcp/servers/s1/refresh', () => HttpResponse.json(srv)),
    http.delete('/api/mcp/servers/s1', () => new HttpResponse(null, { status: 204 })),
  )
  expect((await refreshServer(api, 's1')).id).toBe('s1')
  await expect(deleteServer(api, 's1')).resolves.toBeUndefined()
})
