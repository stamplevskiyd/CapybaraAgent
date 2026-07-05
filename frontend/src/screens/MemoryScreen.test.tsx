import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, http, HttpResponse } from '../test/msw'
import { AuthProvider } from '../auth/AuthContext'
import { MemoryScreen } from './MemoryScreen'

beforeEach(() =>
  localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'r' })),
)

const fact = {
  id: '1',
  category: 'personal',
  content: 'Любит чай',
  source: 'manual',
  created_at: '2026-07-05T10:00:00Z',
  updated_at: '2026-07-05T10:00:00Z',
}

function renderScreen() {
  return render(
    <AuthProvider>
      <MemoryScreen />
    </AuthProvider>,
  )
}

test('renders facts and adds a new one', async () => {
  const created = { ...fact, id: '2', content: 'Пьёт кофе по утрам', category: 'preference' }
  server.use(
    http.get('/api/memory/facts', () => HttpResponse.json([fact])),
    http.get('/api/memory/settings', () => HttpResponse.json({ auto_capture: true })),
    http.post('/api/memory/facts', () => HttpResponse.json(created, { status: 201 })),
  )
  renderScreen()

  expect(await screen.findByText('Любит чай')).toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: /Добавить факт/ }))
  await userEvent.type(screen.getByLabelText('Текст факта'), 'Пьёт кофе по утрам')
  await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))

  expect(await screen.findByText('Пьёт кофе по утрам')).toBeInTheDocument()
})

test('deletes a fact', async () => {
  server.use(
    http.get('/api/memory/facts', () => HttpResponse.json([fact])),
    http.get('/api/memory/settings', () => HttpResponse.json({ auto_capture: true })),
    http.delete('/api/memory/facts/1', () => new HttpResponse(null, { status: 204 })),
  )
  renderScreen()
  expect(await screen.findByText('Любит чай')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Удалить' }))
  await waitFor(() => expect(screen.queryByText('Любит чай')).not.toBeInTheDocument())
})

test('toggles auto-capture', async () => {
  let patched: unknown = null
  server.use(
    http.get('/api/memory/facts', () => HttpResponse.json([])),
    http.get('/api/memory/settings', () => HttpResponse.json({ auto_capture: true })),
    http.patch('/api/memory/settings', async ({ request }) => {
      patched = await request.json()
      return HttpResponse.json({ auto_capture: false })
    }),
  )
  renderScreen()
  const toggle = await screen.findByLabelText('Авто-запоминание')
  await userEvent.click(toggle)
  await waitFor(() => expect(patched).toEqual({ auto_capture: false }))
})
