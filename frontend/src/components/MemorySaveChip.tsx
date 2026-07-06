/**
 * Collapsible footer chip showing what the assistant auto-captured to long-term memory
 * this turn. Symmetric with ToolCallCard but rendered below the answer, since saving
 * happens after the reply. Collapsed by default; expands to the list of saved facts.
 */
import { useState } from 'react'
import { Check, ChevronRight, Save } from 'lucide-react'
import styles from './ToolCallCard.module.css'
import { pluralFacts } from './plural'

/** Props for the MemorySaveChip component. */
export interface MemorySaveChipProps {
  /** List of facts that were saved to memory this turn. */
  saves: { content: string; category: string }[]
}

/**
 * Renders a collapsible chip summarising memory-save events for the current assistant turn.
 *
 * Returns null when saves is empty so no chip appears on turns with no memory activity.
 */
export function MemorySaveChip({ saves }: MemorySaveChipProps) {
  const [open, setOpen] = useState(false)
  if (saves.length === 0) return null
  const label = `Запомнил ${saves.length} ${pluralFacts(saves.length)}`
  return (
    <div className={styles.card}>
      <button
        type="button"
        className={styles.header}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <Save size={15} />
        <span className={styles.label}>{label}</span>
        <Check size={15} className={styles.check} />
        <ChevronRight
          size={15}
          className={`${styles.chevron} ${open ? styles.chevronOpen : ''}`}
        />
      </button>
      {open && (
        <div className={styles.body}>
          {saves.map((s, i) => (
            <div key={i} className={styles.field}>
              <span className={styles.fieldLabel}>{s.category}:</span>
              <span className={styles.value}>{s.content}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
