import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Composer } from './Composer'

test('submits on Enter and clears', async () => {
  const onSend = vi.fn()
  render(<Composer onSend={onSend} />)
  const box = screen.getByRole('textbox')
  await userEvent.type(box, 'Привет{Enter}')
  expect(onSend).toHaveBeenCalledWith('Привет')
  expect(box).toHaveValue('')
})

test('does not submit empty input', async () => {
  const onSend = vi.fn()
  render(<Composer onSend={onSend} />)
  await userEvent.type(screen.getByRole('textbox'), '{Enter}')
  expect(onSend).not.toHaveBeenCalled()
})
