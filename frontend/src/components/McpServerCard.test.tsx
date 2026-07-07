import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { McpServerCard } from './McpServerCard'
import type { McpServerOut } from '../api/types'

const server: McpServerOut = {
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

function noop() {}

test('renders name, url, tool count and fires toggle', async () => {
  const onToggle = vi.fn()
  render(
    <McpServerCard
      server={server}
      onToggle={onToggle}
      onRefresh={async () => {}}
      onDelete={noop}
      onToggleTool={noop}
    />,
  )
  expect(screen.getByText('github')).toBeInTheDocument()
  expect(screen.getByText('https://mcp.example/github')).toBeInTheDocument()
  expect(screen.getByText(/1 инструмент/)).toBeInTheDocument()

  await userEvent.click(screen.getByRole('checkbox', { name: 'Сервер включён' }))
  expect(onToggle).toHaveBeenCalledWith(false)
})

test('shows the error text when last_error is set', () => {
  render(
    <McpServerCard
      server={{ ...server, last_error: 'boom', last_connected_at: null }}
      onToggle={noop}
      onRefresh={async () => {}}
      onDelete={noop}
      onToggleTool={noop}
    />,
  )
  expect(screen.getByText('boom')).toBeInTheDocument()
})

test('confirms before deleting', async () => {
  const onDelete = vi.fn()
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  render(
    <McpServerCard
      server={server}
      onToggle={noop}
      onRefresh={async () => {}}
      onDelete={onDelete}
      onToggleTool={noop}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: 'Удалить сервер' }))
  expect(onDelete).toHaveBeenCalled()
})
