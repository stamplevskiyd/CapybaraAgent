/**
 * Active chat thread: message list, markdown assistant content, action bar (Copy / Reload),
 * and a ScrollToBottom affordance. Must be mounted inside an AssistantRuntimeProvider.
 *
 * Uses assistant-ui headless primitives styled via Thread.module.css (liquid-glass palette).
 * User messages render as right-aligned bubbles; assistant messages render with the CapyLogo
 * glyph, markdown content (via MarkdownText → MarkdownTextPrimitive), and a hover action bar.
 */
import { ThreadPrimitive, MessagePrimitive, ActionBarPrimitive, useMessage } from '@assistant-ui/react'
import { ArrowDown, Copy, RefreshCw } from 'lucide-react'
import { CapyLogo } from './CapyLogo'
import { MarkdownText } from './MessageMarkdown'
import { ToolCallCard } from './ToolCallCard'
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

/** Three-dot "thinking" indicator shown while the model is working but not yet typing text. */
function TypingIndicator() {
  return (
    <div className={styles.typing} role="status" aria-label="Модель печатает">
      <span className={styles.typingDot} />
      <span className={styles.typingDot} />
      <span className={styles.typingDot} />
    </div>
  )
}

/**
 * Show the typing indicator whenever the turn is still running but no answer text has
 * started streaming yet — before the first token AND in the gaps between tool calls (where
 * the message already has tool-call parts, so `hasContent` is true and would otherwise hide
 * the indicator, leaving a multi-tool reply looking frozen). Once the model emits text, the
 * streaming text is the feedback and the dots hide.
 */
function ThinkingWhileWorking() {
  const working = useMessage((m) => {
    if (m.status?.type !== 'running') return false
    return !m.content.some((part) => part.type === 'text' && part.text.length > 0)
  })
  return working ? <TypingIndicator /> : null
}

/**
 * Assistant message: CapyLogo avatar + markdown content + hover action bar (Copy / Reload).
 *
 * Passes MarkdownText as the Text renderer so that MarkdownTextPrimitive reads the message
 * content from the assistant-ui context, applies GFM + sanitize, and routes fenced code
 * blocks to CodeBlock.
 *
 * While the last assistant message is still empty (streaming, before its first token) a
 * typing indicator is shown so the reply never looks frozen. The action bar appears only
 * once there is content, and Reload (regenerate) is gated to the last message — regenerating
 * always targets the latest turn, so offering it on older replies would mislead.
 */
function AssistantMessage() {
  return (
    <MessagePrimitive.Root className={styles.assistantRow}>
      <div className={styles.avatar}>
        <CapyLogo size={20} />
      </div>
      <div className={styles.assistantContent}>
        <MessagePrimitive.Content
          components={{ Text: MarkdownText, tools: { Fallback: ToolCallCard } }}
        />
        <MessagePrimitive.If last>
          <ThinkingWhileWorking />
        </MessagePrimitive.If>
        <MessagePrimitive.If hasContent>
          <ActionBarPrimitive.Root className={styles.actions}>
            <ActionBarPrimitive.Copy className={styles.actionBtn}>
              <Copy size={15} />
            </ActionBarPrimitive.Copy>
            <MessagePrimitive.If last>
              <ActionBarPrimitive.Reload
                className={styles.actionBtn}
                aria-label="Перегенерировать ответ"
              >
                <RefreshCw size={15} />
              </ActionBarPrimitive.Reload>
            </MessagePrimitive.If>
          </ActionBarPrimitive.Root>
        </MessagePrimitive.If>
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
