/** Presentational list item for a single chat: star toggle, title/inline-rename, menu button. */
import { useState, useEffect, type KeyboardEvent } from 'react'
import { Star, MoreHorizontal } from 'lucide-react'
import type { ChatOut } from '../api/types'
import styles from './Sidebar.module.css'

/** One chat row. Star toggles favorite; the ⋯ button opens the context menu at its anchor. */
export function ChatListItem({
  chat,
  active,
  renaming,
  onSelect,
  onToggleFavorite,
  onOpenMenu,
  onRenameCommit,
  onRenameCancel,
}: {
  chat: ChatOut
  active: boolean
  renaming: boolean
  onSelect: () => void
  onToggleFavorite: () => void
  onOpenMenu: (anchor: DOMRect) => void
  onRenameCommit: (title: string) => void
  onRenameCancel: () => void
}) {
  const [draft, setDraft] = useState(chat.title)

  useEffect(() => {
    if (renaming) setDraft(chat.title)
  }, [renaming, chat.title])

  if (renaming) {
    const commit = () => {
      const t = draft.trim()
      if (t) onRenameCommit(t)
      else onRenameCancel()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Enter') {
        e.preventDefault()
        commit()
      } else if (e.key === 'Escape') {
        onRenameCancel()
      }
    }
    return (
      <input
        className={styles.renameInput}
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKey}
        onBlur={commit}
        aria-label="Переименовать чат"
      />
    )
  }

  return (
    <div className={active ? `${styles.chatRow} ${styles.chatRowActive}` : styles.chatRow}>
      <button
        type="button"
        className={chat.is_favorite ? `${styles.star} ${styles.starOn}` : styles.star}
        aria-label={chat.is_favorite ? 'Убрать из избранного' : 'В избранное'}
        onClick={onToggleFavorite}
      >
        <Star size={15} fill={chat.is_favorite ? 'currentColor' : 'none'} />
      </button>
      <button type="button" className={styles.chatTitleBtn} onClick={onSelect}>
        <span className={styles.chatTitle}>{chat.title}</span>
      </button>
      <button
        type="button"
        className={styles.menuBtn}
        aria-label="Меню чата"
        onClick={(e) => onOpenMenu(e.currentTarget.getBoundingClientRect())}
      >
        <MoreHorizontal size={15} />
      </button>
    </div>
  )
}
