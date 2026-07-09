import { act, renderHook, waitFor } from '@testing-library/react'
import type { IStep } from '@chainlit/react-client'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { useChainlitThread } from './useChainlitThread'

const chainlitHooks = vi.hoisted(() => ({
  connect: vi.fn(),
  disconnect: vi.fn(),
  sendMessage: vi.fn(),
  stopTask: vi.fn(),
  useChatData: vi.fn(),
  useChatInteract: vi.fn(),
  useChatMessages: vi.fn(),
  useChatSession: vi.fn(),
  fetch: vi.fn(),
  token: { value: null as string | null },
}))

vi.mock('@chainlit/react-client', () => ({
  useChatData: chainlitHooks.useChatData,
  useChatInteract: chainlitHooks.useChatInteract,
  useChatMessages: chainlitHooks.useChatMessages,
  useChatSession: chainlitHooks.useChatSession,
}))

vi.mock('./client', () => ({
  chainlitClient: { fetch: chainlitHooks.fetch },
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ token: chainlitHooks.token.value }),
}))

describe('useChainlitThread', () => {
  beforeEach(() => {
    chainlitHooks.connect.mockReset()
    chainlitHooks.disconnect.mockReset()
    chainlitHooks.sendMessage.mockReset()
    chainlitHooks.stopTask.mockReset()
    chainlitHooks.fetch.mockReset()
    chainlitHooks.fetch.mockResolvedValue({ json: async () => ({}) })
    chainlitHooks.token.value = null
    chainlitHooks.useChatData.mockReturnValue({ loading: false })
    chainlitHooks.useChatInteract.mockReturnValue({
      sendMessage: chainlitHooks.sendMessage,
      stopTask: chainlitHooks.stopTask,
    })
    chainlitHooks.useChatMessages.mockReturnValue({ messages: [] })
    chainlitHooks.useChatSession.mockReturnValue({
      connect: chainlitHooks.connect,
      disconnect: chainlitHooks.disconnect,
      session: undefined,
    })
  })

  test('connects the Chainlit session when mounted', async () => {
    renderHook(() => useChainlitThread())

    await waitFor(() => expect(chainlitHooks.connect).toHaveBeenCalledWith({ userEnv: {} }))
  })

  test('authenticates with the app JWT before connecting when a token is present', async () => {
    chainlitHooks.token.value = 'jwt-123'

    renderHook(() => useChainlitThread())

    await waitFor(() =>
      expect(chainlitHooks.fetch).toHaveBeenCalledWith(
        'POST',
        '/auth/header',
        undefined,
        undefined,
        { Authorization: 'Bearer jwt-123' },
      ),
    )
    await waitFor(() => expect(chainlitHooks.connect).toHaveBeenCalledWith({ userEnv: {} }))
    expect(chainlitHooks.fetch.mock.invocationCallOrder[0]).toBeLessThan(
      chainlitHooks.connect.mock.invocationCallOrder[0],
    )
  })

  test('skips the auth handshake when there is no token', async () => {
    renderHook(() => useChainlitThread())

    await waitFor(() => expect(chainlitHooks.connect).toHaveBeenCalled())
    expect(chainlitHooks.fetch).not.toHaveBeenCalled()
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
