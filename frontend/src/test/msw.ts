import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'

// Benign defaults for endpoints the chat shell touches on mount, so tests that are not
// about them get empty data instead of MSW warnings: Chainlit header auth + thread list,
// and Capybara's chat-prefs.
const defaultHandlers = [
  http.post('/chainlit/auth/header', () => HttpResponse.json({ success: true })),
  http.post('/chainlit/project/threads', () =>
    HttpResponse.json({ pageInfo: { hasNextPage: false, startCursor: null, endCursor: null }, data: [] }),
  ),
  http.get('/api/chat-prefs', () => HttpResponse.json([])),
  http.put('/api/chat-prefs/:threadId', ({ params }) =>
    HttpResponse.json({ thread_id: params.threadId, is_favorite: false, model: null }),
  ),
]

export const server = setupServer(...defaultHandlers)
export { http, HttpResponse }
