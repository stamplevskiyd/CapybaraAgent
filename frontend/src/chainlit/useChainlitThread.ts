import { useCallback, useMemo } from 'react'
import { useChatData, useChatInteract, useChatMessages } from '@chainlit/react-client'
import { convertChainlitMessage } from './convertChainlitMessage'

export function useChainlitThread() {
  const { messages: chainlitMessages } = useChatMessages()
  const { loading } = useChatData()
  const { sendMessage, stopTask } = useChatInteract()

  const messages = useMemo(
    () => chainlitMessages.map(convertChainlitMessage).filter((message) => message !== null),
    [chainlitMessages],
  )

  const send = useCallback(
    async (content: string) => {
      sendMessage({
        name: 'user',
        type: 'user_message',
        output: content,
      })
    },
    [sendMessage],
  )

  return {
    messages,
    sending: loading,
    cancel: stopTask,
    send,
  }
}
