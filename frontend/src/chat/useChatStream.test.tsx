import { renderHook, act, waitFor } from '@testing-library/react'
import { server, http, HttpResponse } from '../test/msw'
import { AuthProvider } from '../auth/AuthContext'
import { useChatStream } from './useChatStream'

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <AuthProvider>{children}</AuthProvider>
)
beforeEach(() =>
  localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'r' })),
)

test('streams assistant deltas into a message', async () => {
  server.use(
    http.post('/api/chats/c1/messages', () => {
      const body =
        'event: delta\ndata: {"text":"Привет"}\n\n' +
        'event: delta\ndata: {"text":", Роман"}\n\n' +
        'event: done\ndata: {"message_id":"m9"}\n\n'
      return new HttpResponse(body, {
        headers: { 'Content-Type': 'text/event-stream' },
      })
    }),
  )
  const { result } = renderHook(() => useChatStream('c1'), { wrapper })
  await act(async () => {
    await result.current.send('Привет')
  })
  await waitFor(() => expect(result.current.sending).toBe(false))
  const assistant = result.current.messages.find((m) => m.role === 'assistant')!
  expect(assistant.content).toBe('Привет, Роман')
  expect(assistant.streaming).toBe(false)
})
