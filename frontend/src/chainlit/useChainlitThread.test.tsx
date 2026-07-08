import { act, renderHook } from '@testing-library/react'
import type { IStep } from '@chainlit/react-client'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { useChainlitThread } from './useChainlitThread'

const chainlitHooks = vi.hoisted(() => ({
  sendMessage: vi.fn(),
  stopTask: vi.fn(),
  useChatData: vi.fn(),
  useChatInteract: vi.fn(),
  useChatMessages: vi.fn(),
}))

vi.mock('@chainlit/react-client', () => ({
  useChatData: chainlitHooks.useChatData,
  useChatInteract: chainlitHooks.useChatInteract,
  useChatMessages: chainlitHooks.useChatMessages,
}))

describe('useChainlitThread', () => {
  beforeEach(() => {
    chainlitHooks.sendMessage.mockReset()
    chainlitHooks.stopTask.mockReset()
    chainlitHooks.useChatData.mockReturnValue({ loading: false })
    chainlitHooks.useChatInteract.mockReturnValue({
      sendMessage: chainlitHooks.sendMessage,
      stopTask: chainlitHooks.stopTask,
    })
    chainlitHooks.useChatMessages.mockReturnValue({ messages: [] })
  })

  test('returns converted Chainlit messages in the existing UI shape', () => {
    const messages: IStep[] = [
      {
        id: 'u1',
        name: 'User',
        type: 'user_message',
        output: 'Hello',
        createdAt: '2026-07-08T00:00:00Z',
      },
      {
        id: 'tool-1',
        name: 'internal',
        type: 'tool',
        output: 'hidden at top level',
        createdAt: '2026-07-08T00:00:00Z',
      },
    ]
    chainlitHooks.useChatMessages.mockReturnValue({ messages })

    const { result } = renderHook(() => useChainlitThread())

    expect(result.current.messages).toEqual([
      {
        id: 'u1',
        role: 'user',
        content: 'Hello',
        streaming: false,
        error: undefined,
        toolCalls: undefined,
      },
    ])
  })

  test('sends user text through the Chainlit client hook', async () => {
    const { result } = renderHook(() => useChainlitThread())

    await act(async () => {
      await result.current.send('Hello Chainlit')
    })

    expect(chainlitHooks.sendMessage).toHaveBeenCalledWith({
      name: 'user',
      type: 'user_message',
      output: 'Hello Chainlit',
    })
  })
})
