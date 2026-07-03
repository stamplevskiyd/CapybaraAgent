import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server, http, HttpResponse } from '../test/msw'
import { AuthProvider } from '../auth/AuthContext'
import { AuthScreen } from './AuthScreen'

const renderScreen = () =>
  render(
    <AuthProvider>
      <AuthScreen />
    </AuthProvider>,
  )

beforeEach(() => localStorage.clear())

test('shows inline error on invalid login', async () => {
  server.use(http.post('/api/auth/login', () => new HttpResponse(null, { status: 401 })))
  renderScreen()
  await userEvent.type(screen.getByLabelText('Логин'), 'roman')
  await userEvent.type(screen.getByLabelText('Пароль'), 'wrongpass')
  await userEvent.click(screen.getByRole('button', { name: 'Войти' }))
  expect(await screen.findByText('Неверный логин или пароль')).toBeInTheDocument()
})

test('can switch to register mode', async () => {
  renderScreen()
  await userEvent.click(screen.getByText('Создать пользователя'))
  expect(screen.getByRole('button', { name: 'Создать аккаунт' })).toBeInTheDocument()
  expect(screen.getByLabelText('Имя')).toBeInTheDocument()
})
