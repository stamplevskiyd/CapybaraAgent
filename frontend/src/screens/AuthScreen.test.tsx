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

test('shows conflict error on 409 during registration', async () => {
  server.use(http.post('/api/users', () => new HttpResponse(null, { status: 409 })))
  renderScreen()
  await userEvent.click(screen.getByText('Создать пользователя'))
  await userEvent.type(screen.getByLabelText('Имя'), 'Роман')
  await userEvent.type(screen.getByLabelText('Логин'), 'roman')
  await userEvent.type(screen.getByLabelText('Пароль'), 'secret123')
  await userEvent.click(screen.getByRole('button', { name: 'Создать аккаунт' }))
  expect(await screen.findByText('Логин уже занят')).toBeInTheDocument()
})
