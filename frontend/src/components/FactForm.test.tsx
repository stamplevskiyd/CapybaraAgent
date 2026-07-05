import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FactForm } from './FactForm'

test('submits entered content and selected category', async () => {
  const onSubmit = vi.fn()
  render(<FactForm onSubmit={onSubmit} onCancel={() => {}} />)

  await userEvent.type(screen.getByLabelText('Текст факта'), 'Любит горы')
  await userEvent.selectOptions(screen.getByLabelText('Категория'), 'project')
  await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))

  expect(onSubmit).toHaveBeenCalledWith('Любит горы', 'project')
})

test('save is disabled until content is non-blank', async () => {
  render(<FactForm onSubmit={() => {}} onCancel={() => {}} />)
  expect(screen.getByRole('button', { name: 'Сохранить' })).toBeDisabled()
  await userEvent.type(screen.getByLabelText('Текст факта'), 'x')
  expect(screen.getByRole('button', { name: 'Сохранить' })).toBeEnabled()
})
