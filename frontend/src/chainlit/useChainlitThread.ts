import { useCallback, useEffect, useMemo } from 'react'
import {
  useChatData,
  useChatInteract,
  useChatMessages,
  useChatSession,
} from '@chainlit/react-client'
import type { ChatMessage } from '../chat/useChatStream'
import { convertChainlitMessage } from './convertChainlitMessage'

function isChatMessage(message: ChatMessage | null): message is ChatMessage {
  return message !== null
}

export function useChainlitThread() {
  const { messages: chainlitMessages } = useChatMessages()
  const { loading } = useChatData()
  const { sendMessage, stopTask } = useChatInteract()
  const { connect, disconnect, session } = useChatSession()

  useEffect(() => {
    if (!session) void connect({ userEnv: {} })
    return () => disconnect()
  }, [connect, disconnect, session])

  const messages = useMemo(
    () => chainlitMessages.map(convertChainlitMessage).filter(isChatMessage),
    [chainlitMessages],
  )

  const send = useCallback(
    async (content: string, _chatIdOverride?: string) => {
      void _chatIdOverride
      sendMessage({
        name: 'user',
        type: 'user_message',
        output: content,
      })
    },
    [sendMessage],
  )

  const loadHistory = useCallback(async () => {}, [])
  const regenerate = useCallback(async () => {}, [])

  return useMemo(
    () => ({
      messages,
      sending: loading,
      loadingHistory: false,
      send,
      loadHistory,
      cancel: stopTask,
      regenerate,
    }),
    [loadHistory, loading, messages, regenerate, send, stopTask],
  )
}
