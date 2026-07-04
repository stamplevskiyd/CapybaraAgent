/** Bridge our chat store to assistant-ui via ExternalStoreRuntime. */
import { useExternalStoreRuntime, type AppendMessage } from '@assistant-ui/react'
import { convertMessage } from './convertMessage'
import type { ChatMessage } from './useChatStream'

/**
 * Extract the plain text from the first text part of an AppendMessage.
 *
 * assistant-ui converts a string `CreateAppendMessage` shorthand into
 * `{ content: [{ type: 'text', text: string }] }` before invoking `onNew`.
 */
function textOf(message: AppendMessage): string {
  const part = message.content[0]
  return part?.type === 'text' ? part.text : ''
}

/**
 * Build an assistant-ui `AssistantRuntime` backed by our local chat store.
 *
 * Wraps `useExternalStoreRuntime` from `@assistant-ui/react`, converting
 * our `ChatMessage` array via `convertMessage` and routing `onNew` /
 * `onReload` / `onCancel` to the provided callbacks.
 */
export function useChatRuntime(opts: {
  /** Current message list from the chat store. */
  messages: ChatMessage[]
  /** Whether a streaming response is in flight. */
  isRunning: boolean
  /** Called when the user submits a new message. */
  onSend: (text: string) => Promise<void>
  /** Called when the user requests regeneration of the last reply. */
  onReload: () => Promise<void>
  /** Called when the user cancels a running stream. */
  onCancel: () => void
}) {
  return useExternalStoreRuntime<ChatMessage>({
    messages: opts.messages,
    isRunning: opts.isRunning,
    convertMessage,
    onNew: async (message: AppendMessage) => {
      await opts.onSend(textOf(message))
    },
    // The ExternalStoreAdapter.onReload signature passes (parentId, config);
    // we ignore those and simply forward to our own onReload().
    onReload: async () => {
      await opts.onReload()
    },
    onCancel: async () => {
      opts.onCancel()
    },
  })
}
