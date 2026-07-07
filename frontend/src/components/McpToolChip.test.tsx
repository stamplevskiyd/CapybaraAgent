import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { McpToolChip } from './McpToolChip'
import type { McpToolOut } from '../api/types'

const tool: McpToolOut = { id: 't1', name: 'search', description: 'Search repos', enabled: true }

test('renders the tool name and fires onToggle', async () => {
  const onToggle = vi.fn()
  render(<McpToolChip tool={tool} onToggle={onToggle} />)
  const cb = screen.getByRole('checkbox', { name: 'Инструмент search' })
  expect(cb).toBeChecked()
  expect(screen.getByText('search')).toBeInTheDocument()
  await userEvent.click(cb)
  expect(onToggle).toHaveBeenCalledWith(false)
})
