import { useCallback, useEffect, useMemo } from 'react'
import {
  useChatData,
  useChatInteract,
  useChatMessages,
  useChatSession,
} from '@chainlit/react-client'
import type { ChatMessage } from '../chat/useChatStream'
import { useAuth } from '../auth/AuthContext'
import { chainlitClient } from './client'
import { convertChainlitMessage } from './convertChainlitMessage'

function isChatMessage(message: ChatMessage | null): message is ChatMessage {
  return message !== null
}

export function useChainlitThread() {
  const { messages: chainlitMessages } = useChatMessages()
  const { loading } = useChatData()
  const { sendMessage, stopTask } = useChatInteract()
  const { connect, disconnect, session } = useChatSession()
  const { token } = useAuth()

  useEffect(() => {
    if (session) return
    let cancelled = false
    void (async () => {
      // Chainlit auth is header-based: hand it the app's JWT so its header_auth_callback
      // sets the session cookie the socket then connects with. Without a token we still
      // connect (unauthenticated) and let the backend reject if auth is required.
      if (token) {
        try {
          await chainlitClient.fetch('POST', '/auth/header', undefined, undefined, {
            Authorization: `Bearer ${token}`,
          })
        } catch {
          // Expired/invalid token: connect() will surface the failure via the client's
          // on401 handler rather than us swallowing it here.
        }
      }
      if (!cancelled) await connect({ userEnv: {} })
    })()
    return () => {
      cancelled = true
      disconnect()
    }
  }, [connect, disconnect, session, token])

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
