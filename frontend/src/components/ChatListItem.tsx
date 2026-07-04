/** Presentational list item for a single chat entry in the Sidebar. */
import { MessageSquare } from 'lucide-react'
import type { ChatOut } from '../api/types'
import styles from './Sidebar.module.css'

/** Renders one chat row: chat icon + title, active or inactive styling. */
export function ChatListItem({
  chat,
  active,
  onSelect,
}: {
  chat: ChatOut
  active: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      className={active ? `${styles.chatItem} ${styles.chatItemActive}` : styles.chatItem}
      onClick={onSelect}
    >
      <span className={active ? `${styles.chatIcon} ${styles.chatIconActive}` : styles.chatIcon}>
        <MessageSquare size={16} />
      </span>
      <span className={styles.chatTitle}>{chat.title}</span>
    </button>
  )
}
