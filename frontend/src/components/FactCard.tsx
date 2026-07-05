/** A single fact: coloured category tag, content, date, and hover edit/delete actions. */
import { Pencil, Trash2 } from 'lucide-react'
import type { FactOut } from '../api/types'
import { CATEGORY_BY_VALUE } from '../memory/categories'
import styles from './FactCard.module.css'

/** Format an ISO timestamp as a RU long date, e.g. "5 июля 2026 г.". */
function formatDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })
}

export function FactCard({
  fact,
  onEdit,
  onDelete,
}: {
  fact: FactOut
  onEdit: () => void
  onDelete: () => void
}) {
  const meta = CATEGORY_BY_VALUE[fact.category]
  return (
    <div className={styles.card}>
      <div className={styles.head}>
        <span className={styles.tag} style={{ color: meta.color, background: meta.bg }}>
          {meta.label}
        </span>
        <div className={styles.actions}>
          <button type="button" className={styles.iconBtn} aria-label="Редактировать" onClick={onEdit}>
            <Pencil size={14} />
          </button>
          <button type="button" className={styles.iconBtn} aria-label="Удалить" onClick={onDelete}>
            <Trash2 size={14} />
          </button>
        </div>
      </div>
      <div className={styles.content}>{fact.content}</div>
      <div className={styles.date}>{formatDate(fact.created_at)}</div>
    </div>
  )
}
