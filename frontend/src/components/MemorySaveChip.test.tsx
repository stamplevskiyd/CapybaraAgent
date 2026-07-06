import { expect, test } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemorySaveChip } from './MemorySaveChip'

test('shows the saved-fact count and expands to the list', async () => {
  render(
    <MemorySaveChip
      saves={[
        { content: 'Любит чай', category: 'preference' },
        { content: 'Пишет на Python', category: 'personal' },
      ]}
    />,
  )
  expect(screen.getByText('Запомнил 2 факта')).toBeInTheDocument()
  // collapsed by default
  expect(screen.queryByText('Любит чай')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button'))
  expect(screen.getByText('Любит чай')).toBeInTheDocument()
  expect(screen.getByText('Пишет на Python')).toBeInTheDocument()
})

test('renders nothing when saves is empty', () => {
  const { container } = render(<MemorySaveChip saves={[]} />)
  expect(container.firstChild).toBeNull()
})
