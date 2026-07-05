/** Floating context menu for a chat row: rename, favorite toggle, and delete (with confirm). */
import { useState } from 'react'
import { createPortal } from 'react-dom'
import { Pencil, Star, Trash2 } from 'lucide-react'
import styles from './Sidebar.module.css'

/** Rendered at (x, y); a click on the backdrop closes it. Delete arms a confirm on first click. */
export function ChatContextMenu({
  x,
  y,
  isFavorite,
  onRename,
  onToggleFavorite,
  onDelete,
  onClose,
}: {
  x: number
  y: number
  isFavorite: boolean
  onRename: () => void
  onToggleFavorite: () => void
  onDelete: () => void
  onClose: () => void
}) {
  const [confirming, setConfirming] = useState(false)
  // Portal to <body>: the sidebar's backdrop-filter creates a containing block +
  // stacking context that would otherwise trap this position:fixed menu inside the
  // sidebar — the part overflowing into the main pane paints behind it and stops
  // registering clicks. Rendering at the document root frees it to sit above all.
  return createPortal(
    <div className={styles.menuBackdrop} onClick={onClose} role="presentation">
      <div
        className={styles.menu}
        style={{ left: x, top: y }}
        role="menu"
        onClick={(e) => e.stopPropagation()}
      >
        <button type="button" className={styles.menuItem} role="menuitem" onClick={onRename}>
          <Pencil size={14} />
          Переименовать
        </button>
        <button
          type="button"
          className={styles.menuItem}
          role="menuitem"
          onClick={onToggleFavorite}
        >
          <Star size={14} />
          {isFavorite ? 'Убрать из избранного' : 'В избранное'}
        </button>
        <div className={styles.menuSep} />
        <button
          type="button"
          className={`${styles.menuItem} ${styles.menuItemDanger}`}
          role="menuitem"
          onClick={() => (confirming ? onDelete() : setConfirming(true))}
        >
          <Trash2 size={14} />
          {confirming ? 'Точно удалить?' : 'Удалить'}
        </button>
      </div>
    </div>,
    document.body,
  )
}
