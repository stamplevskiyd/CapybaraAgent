import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConnectWizard } from './ConnectWizard'
import { ApiError } from '../api/client'
import type { McpServerOut } from '../api/types'

const created: McpServerOut = {
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

test('submits name/url and shows the success step with tools', async () => {
  const onConnect = vi.fn().mockResolvedValue(created)
  const onClose = vi.fn()
  render(<ConnectWizard onConnect={onConnect} onClose={onClose} />)

  await userEvent.type(screen.getByLabelText('Название'), 'github')
  await userEvent.type(screen.getByLabelText('URL'), 'https://mcp.example/github')
  await userEvent.click(screen.getByRole('button', { name: 'Подключить' }))

  expect(onConnect).toHaveBeenCalledWith('github', 'https://mcp.example/github', {})
  expect(await screen.findByText('Сервер подключён')).toBeInTheDocument()
  expect(screen.getByText('search')).toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: 'Готово' }))
  expect(onClose).toHaveBeenCalled()
})

test('adds a header row and includes it in the request', async () => {
  const onConnect = vi.fn().mockResolvedValue(created)
  render(<ConnectWizard onConnect={onConnect} onClose={() => {}} />)

  await userEvent.type(screen.getByLabelText('Название'), 'github')
  await userEvent.type(screen.getByLabelText('URL'), 'https://x')
  await userEvent.click(screen.getByRole('button', { name: 'Добавить заголовок' }))
  await userEvent.type(screen.getByLabelText('Ключ заголовка 1'), 'Authorization')
  await userEvent.type(screen.getByLabelText('Значение заголовка 1'), 'Bearer x')
  await userEvent.click(screen.getByRole('button', { name: 'Подключить' }))

  expect(onConnect).toHaveBeenCalledWith('github', 'https://x', { Authorization: 'Bearer x' })
})

test('shows the error detail and allows going back', async () => {
  const onConnect = vi
    .fn()
    .mockRejectedValue(new ApiError(400, JSON.stringify({ detail: 'bad handshake' })))
  render(<ConnectWizard onConnect={onConnect} onClose={() => {}} />)

  await userEvent.type(screen.getByLabelText('Название'), 'x')
  await userEvent.type(screen.getByLabelText('URL'), 'https://x')
  await userEvent.click(screen.getByRole('button', { name: 'Подключить' }))

  expect(await screen.findByText('bad handshake')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Назад' }))
  expect(screen.getByLabelText('Название')).toHaveValue('x')
})

test('does not close modal when clicking X during checking step', async () => {
  let resolveConnect: (value: McpServerOut) => void
  const onConnect = vi.fn()
    .mockImplementation(() => new Promise((resolve) => {
      resolveConnect = resolve
    }))
  const onClose = vi.fn()
  render(<ConnectWizard onConnect={onConnect} onClose={onClose} />)

  await userEvent.type(screen.getByLabelText('Название'), 'test')
  await userEvent.type(screen.getByLabelText('URL'), 'https://example.com')
  await userEvent.click(screen.getByRole('button', { name: 'Подключить' }))

  expect(await screen.findByText('Проверяем соединение…')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Закрыть' }))
  expect(onClose).not.toHaveBeenCalled()

  // Cleanup: resolve the promise
  resolveConnect!(created)
})
