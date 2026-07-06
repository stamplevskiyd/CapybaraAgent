import { render, screen, fireEvent } from '@testing-library/react'
import type { ToolCallMessagePartProps } from '@assistant-ui/react'
import { ToolCallCard } from './ToolCallCard'

function renderCard(props: Partial<ToolCallMessagePartProps> = {}) {
  const base: Partial<ToolCallMessagePartProps> = {
    toolName: 'recall',
    args: { query: 'хобби' },
    result: '- [personal] походы',
    status: { type: 'complete' as const },
  }
  // assistant-ui passes many props; the component only reads the subset above.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return render(<ToolCallCard {...(base as any)} {...(props as any)} />)
}

test('shows the localized label and expands to reveal args and result', () => {
  renderCard()
  expect(screen.getByText('Поиск в памяти')).toBeInTheDocument()
  // collapsed: result not shown yet
  expect(screen.queryByText(/походы/)).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button'))
  expect(screen.getByText(/походы/)).toBeInTheDocument()
  expect(screen.getByText(/хобби/)).toBeInTheDocument()
})

test('shows a running state while the tool executes', () => {
  renderCard({ result: undefined, status: { type: 'running' } as never })
  expect(screen.getByRole('status')).toBeInTheDocument()
})

test('falls back to the raw tool name for unknown tools', () => {
  renderCard({ toolName: 'weather' })
  expect(screen.getByText('weather')).toBeInTheDocument()
})
