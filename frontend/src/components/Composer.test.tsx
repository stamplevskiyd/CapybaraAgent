import React from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AssistantRuntimeProvider } from '@assistant-ui/react'
import { renderHook } from '@testing-library/react'
import { useChatRuntime } from '../chat/runtime'
import { Composer } from './Composer'

const MODELS = ['llama3.1:8b', 'qwen2.5:14b']

function withRuntime(ui: (onSend: ReturnType<typeof vi.fn>) => React.ReactNode) {
  const onSend = vi.fn().mockResolvedValue(undefined)
  const { result } = renderHook(() =>
    useChatRuntime({
      messages: [],
      isRunning: false,
      onSend,
      onReload: vi.fn(),
      onCancel: vi.fn(),
    }),
  )
  render(<AssistantRuntimeProvider runtime={result.current}>{ui(onSend)}</AssistantRuntimeProvider>)
  return onSend
}

test('Send routes text through the runtime onSend', async () => {
  const onSend = withRuntime(() => (
    <Composer
      models={MODELS}
      selectedModel="llama3.1:8b"
      onSelectModel={vi.fn()}
      selectedMode="fast"
      onSelectMode={vi.fn()}
    />
  ))
  await userEvent.type(screen.getByRole('textbox'), 'Привет')
  await userEvent.click(screen.getByLabelText('Отправить'))
  expect(onSend).toHaveBeenCalledWith('Привет')
})

test('send disabled without a valid model', async () => {
  withRuntime(() => (
    <Composer
      models={MODELS}
      selectedModel={null}
      onSelectModel={vi.fn()}
      selectedMode="fast"
      onSelectMode={vi.fn()}
    />
  ))
  await userEvent.type(screen.getByRole('textbox'), 'Привет')
  expect(screen.getByLabelText('Отправить')).toBeDisabled()
})

test('blocks send when selected model is not in the list', async () => {
  withRuntime(() => (
    <Composer
      models={MODELS}
      selectedModel="removed:1b"
      onSelectModel={vi.fn()}
      selectedMode="fast"
      onSelectMode={vi.fn()}
    />
  ))
  await userEvent.type(screen.getByRole('textbox'), 'Привет')
  expect(screen.getByLabelText('Отправить')).toBeDisabled()
})

test('selecting a model calls onSelectModel', async () => {
  const onSelectModel = vi.fn()
  withRuntime(() => (
    <Composer
      models={MODELS}
      selectedModel="llama3.1:8b"
      onSelectModel={onSelectModel}
      selectedMode="fast"
      onSelectMode={vi.fn()}
    />
  ))
  await userEvent.selectOptions(screen.getByLabelText('Модель'), 'qwen2.5:14b')
  expect(onSelectModel).toHaveBeenCalledWith('qwen2.5:14b')
})

test('renders the agent-mode selector and reports a change', async () => {
  const onSelectMode = vi.fn()
  withRuntime(() => (
    <Composer
      models={MODELS}
      selectedModel="llama3.1:8b"
      onSelectModel={vi.fn()}
      selectedMode="fast"
      onSelectMode={onSelectMode}
    />
  ))
  const select = screen.getByLabelText('Режим агента')
  expect(select).toHaveValue('fast')
  await userEvent.selectOptions(select, 'smart')
  expect(onSelectMode).toHaveBeenCalledWith('smart')
})
