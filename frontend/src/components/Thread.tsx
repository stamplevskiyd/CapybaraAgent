/**
 * Active chat thread: message list, markdown assistant content, action bar (Copy / Reload),
 * and a ScrollToBottom affordance. Must be mounted inside an AssistantRuntimeProvider.
 *
 * Uses assistant-ui headless primitives styled via Thread.module.css (liquid-glass palette).
 * User messages render as right-aligned bubbles; assistant messages render with the CapyLogo
 * glyph, markdown content (via MarkdownText → MarkdownTextPrimitive), and a hover action bar.
 */
import { ThreadPrimitive, MessagePrimitive, ActionBarPrimitive } from '@assistant-ui/react'
import { ArrowDown, Copy, RefreshCw } from 'lucide-react'
import { CapyLogo } from './CapyLogo'
import { MarkdownText } from './MessageMarkdown'
import styles from './Thread.module.css'

/**
 * User message: right-aligned bubble with plain text content.
 *
 * Wraps MessagePrimitive.Root and MessagePrimitive.Content (no custom Text renderer
 * needed — user messages are always plain text).
 */
function UserMessage() {
  return (
    <MessagePrimitive.Root className={styles.userRow}>
      <div className={styles.bubble}>
        <MessagePrimitive.Content />
      </div>
    </MessagePrimitive.Root>
  )
}

/**
 * Assistant message: CapyLogo avatar + markdown content + hover action bar (Copy / Reload).
 *
 * Passes MarkdownText as the Text renderer so that MarkdownTextPrimitive reads the message
 * content from the assistant-ui context, applies GFM + sanitize, and routes fenced code
 * blocks to CodeBlock.
 */
function AssistantMessage() {
  return (
    <MessagePrimitive.Root className={styles.assistantRow}>
      <div className={styles.avatar}>
        <CapyLogo size={30} />
      </div>
      <div className={styles.assistantContent}>
        <MessagePrimitive.Content components={{ Text: MarkdownText }} />
        <ActionBarPrimitive.Root className={styles.actions}>
          <ActionBarPrimitive.Copy className={styles.actionBtn}>
            <Copy size={15} />
          </ActionBarPrimitive.Copy>
          <ActionBarPrimitive.Reload className={styles.actionBtn}>
            <RefreshCw size={15} />
          </ActionBarPrimitive.Reload>
        </ActionBarPrimitive.Root>
      </div>
    </MessagePrimitive.Root>
  )
}

/**
 * Renders the full active-chat thread inside a scrollable Viewport.
 *
 * Must be placed inside an AssistantRuntimeProvider. Task 10 mounts this in ChatScreen.
 */
export function Thread() {
  return (
    <ThreadPrimitive.Root className={styles.root}>
      <ThreadPrimitive.Viewport className={styles.viewport}>
        <div className={styles.inner}>
          <ThreadPrimitive.Messages components={{ UserMessage, AssistantMessage }} />
        </div>
        <ThreadPrimitive.ScrollToBottom className={styles.scrollBtn}>
          <ArrowDown size={16} />
        </ThreadPrimitive.ScrollToBottom>
      </ThreadPrimitive.Viewport>
    </ThreadPrimitive.Root>
  )
}
