import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FactCard } from './FactCard'
import type { FactOut } from '../api/types'

const fact: FactOut = {
  id: '1',
  category: 'project',
  content: 'Работает над CapybaraAgent',
  source: 'auto',
  created_at: '2026-07-05T10:00:00Z',
  updated_at: '2026-07-05T10:00:00Z',
}

test('renders the category label, content, and fires edit/delete', async () => {
  const onEdit = vi.fn()
  const onDelete = vi.fn()
  render(<FactCard fact={fact} onEdit={onEdit} onDelete={onDelete} />)

  expect(screen.getByText('Проект')).toBeInTheDocument()
  expect(screen.getByText('Работает над CapybaraAgent')).toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: 'Редактировать' }))
  expect(onEdit).toHaveBeenCalled()
  await userEvent.click(screen.getByRole('button', { name: 'Удалить' }))
  expect(onDelete).toHaveBeenCalled()
})
