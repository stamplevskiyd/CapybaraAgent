/** Single chat message: user bubble (right) or assistant row (glyph + text, optional streaming caret). */
import { CapyLogo } from './CapyLogo'
import type { ChatMessage } from '../chat/useChatStream'
import styles from './Message.module.css'

/** Renders a user or assistant message, including a blinking caret when streaming. */
export function Message({ message }: { message: ChatMessage }) {
  if (message.role === 'user') {
    return (
      <div className={`${styles.messageRow} ${styles.userRow}`}>
        <div className={styles.bubble}>{message.content}</div>
      </div>
    )
  }

  return (
    <div className={`${styles.messageRow} ${styles.assistantRow}`}>
      <div className={styles.avatar}>
        <CapyLogo size={30} />
      </div>
      <div
        className={
          message.error
            ? `${styles.assistantContent} ${styles.errorContent}`
            : styles.assistantContent
        }
      >
        {message.content}
        {message.streaming && <span className={styles.caret} aria-hidden="true" />}
      </div>
    </div>
  )
}
