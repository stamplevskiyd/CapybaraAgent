import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Composer } from './Composer'

const MODELS = ['llama3.1:8b', 'qwen2.5:14b']

test('submits on Enter and clears', async () => {
  const onSend = vi.fn()
  render(<Composer onSend={onSend} models={MODELS} selectedModel="llama3.1:8b" onSelectModel={vi.fn()} />)
  const box = screen.getByRole('textbox')
  await userEvent.type(box, 'Привет{Enter}')
  expect(onSend).toHaveBeenCalledWith('Привет')
  expect(box).toHaveValue('')
})

test('does not submit empty input', async () => {
  const onSend = vi.fn()
  render(<Composer onSend={onSend} models={MODELS} selectedModel="llama3.1:8b" onSelectModel={vi.fn()} />)
  await userEvent.type(screen.getByRole('textbox'), '{Enter}')
  expect(onSend).not.toHaveBeenCalled()
})

test('blocks send when no valid model is selected', async () => {
  const onSend = vi.fn()
  render(<Composer onSend={onSend} models={MODELS} selectedModel={null} onSelectModel={vi.fn()} />)
  await userEvent.type(screen.getByRole('textbox'), 'Привет{Enter}')
  expect(onSend).not.toHaveBeenCalled()
  expect(screen.getByLabelText('Отправить')).toBeDisabled()
})

test('blocks send when selected model is not in the list', async () => {
  const onSend = vi.fn()
  render(<Composer onSend={onSend} models={MODELS} selectedModel="removed:1b" onSelectModel={vi.fn()} />)
  await userEvent.type(screen.getByRole('textbox'), 'Привет{Enter}')
  expect(onSend).not.toHaveBeenCalled()
})

test('selecting a model calls onSelectModel', async () => {
  const onSelectModel = vi.fn()
  render(<Composer onSend={vi.fn()} models={MODELS} selectedModel="llama3.1:8b" onSelectModel={onSelectModel} />)
  await userEvent.selectOptions(screen.getByRole('combobox'), 'qwen2.5:14b')
  expect(onSelectModel).toHaveBeenCalledWith('qwen2.5:14b')
})
