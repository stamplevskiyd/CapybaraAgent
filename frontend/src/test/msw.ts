import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'

// Benign default: any test that mounts useChatStream triggers GET /api/events
// (the persistent push channel).  Return an immediately-complete empty
// text/event-stream so parseSse reads zero events and MSW emits no warning.
const defaultHandlers = [
  http.get('/api/events', () =>
    new HttpResponse('', { headers: { 'Content-Type': 'text/event-stream' } }),
  ),
]

export const server = setupServer(...defaultHandlers)
export { http, HttpResponse }
