// frontend/src/chat/runtime.test.tsx
import { renderHook, act } from '@testing-library/react'
import { useChatRuntime } from './runtime'

test('builds a runtime and exposes append that calls onSend', async () => {
  const onSend = vi.fn().mockResolvedValue(undefined)
  const { result } = renderHook(() =>
    useChatRuntime({
      messages: [{ id: 'm1', role: 'user', content: 'hi', streaming: false }],
      isRunning: false,
      onSend,
      onReload: vi.fn(),
      onCancel: vi.fn(),
    }),
  )
  expect(result.current).toBeTruthy()
  // thread.append(string) is a valid CreateAppendMessage shorthand;
  // the runtime converts it to AppendMessage { content: [{ type:'text', text }] }
  // which our onNew extracts and forwards to opts.onSend.
  await act(async () => {
    await result.current.thread.append('hello')
  })
  expect(onSend).toHaveBeenCalledWith('hello')
})
