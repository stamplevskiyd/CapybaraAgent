import { render, screen } from '@testing-library/react'
import { server, http, HttpResponse } from './test/msw'
import App from './App'

beforeEach(() => localStorage.clear())

test('shows auth screen when logged out', () => {
  render(<App />)
  expect(screen.getByRole('button', { name: 'Войти' })).toBeInTheDocument()
})

test('shows chat view when a session exists', () => {
  server.use(http.get('/api/chats', () => HttpResponse.json([])))
  localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'roman' }))
  render(<App />)
  expect(screen.queryByRole('button', { name: 'Войти' })).not.toBeInTheDocument()
})
