import { useCallback, useEffect, useMemo } from 'react'
import {
  useChatData,
  useChatInteract,
  useChatMessages,
  useChatSession,
} from '@chainlit/react-client'
import { useAuth } from '../auth/AuthContext'
import { chainlitClient } from './client'
import { convertChainlitMessages } from './convertChainlitMessage'
import type { AgentMode } from '../chat/messages'

export function useChainlitThread() {
  const { messages: chainlitMessages, threadId } = useChatMessages()
  const { loading, connected } = useChatData()
  const { sendMessage, stopTask, clear, setIdToResume } = useChatInteract()
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

  const messages = useMemo(() => convertChainlitMessages(chainlitMessages), [chainlitMessages])

  const send = useCallback(
    async (content: string, model?: string | null, mode?: AgentMode) => {
      sendMessage({
        name: 'user',
        type: 'user_message',
        output: content,
        // The backend reads the turn's model AND mode from here.
        metadata: { ...(model ? { model } : {}), ...(mode ? { mode } : {}) },
      })
    },
    [sendMessage],
  )

  /** Switch to a persisted thread: reset the session, then reconnect resuming *id*. */
  const openThread = useCallback(
    (id: string) => {
      clear()
      setIdToResume(id)
    },
    [clear, setIdToResume],
  )

  /** Start a fresh thread: reset the session; the server assigns a new thread id. */
  const newThread = useCallback(() => {
    clear()
  }, [clear])

  return useMemo(
    () => ({
      messages,
      threadId,
      connected: Boolean(connected),
      sending: loading,
      send,
      openThread,
      newThread,
      cancel: stopTask,
    }),
    [connected, loading, messages, newThread, openThread, send, stopTask, threadId],
  )
}
