/**
 * Collapsible tool-call chip, Claude-Code style: icon + localized label with a spinner
 * while the tool runs and a checkmark when it completes. Clicking expands the arguments
 * and result. Rendered as the assistant-ui `tools.Fallback` component inside a message.
 */
import { useState } from 'react'
import type { ToolCallMessagePartComponent } from '@assistant-ui/react'
import { Brain, Check, ChevronRight } from 'lucide-react'
import { cx } from '../cx'
import styles from './ToolCallCard.module.css'

/** Human-readable, localized labels for known tools; unknown tools show their raw name. */
const TOOL_LABELS: Record<string, string> = {
  recall: 'Поиск в памяти',
}

/** Render the tool arguments as a compact single-line string. */
function formatArgs(args: unknown): string {
  if (args && typeof args === 'object') {
    const entries = Object.entries(args as Record<string, unknown>)
    if (entries.length === 1) return String(entries[0][1])
    return JSON.stringify(args)
  }
  return String(args ?? '')
}

/** Collapsible chip that renders a single tool-call message part. */
export const ToolCallCard: ToolCallMessagePartComponent = ({ toolName, args, result, status }) => {
  const [open, setOpen] = useState(false)
  const running = status?.type === 'running' || status?.type === 'requires-action'
  const label = TOOL_LABELS[toolName] ?? toolName
  const resultText = result === undefined || result === null ? '' : String(result)

  return (
    <div className={styles.card}>
      <button
        type="button"
        className={styles.header}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <Brain size={15} />
        <span className={styles.label}>{label}</span>
        {running ? (
          <span className={styles.spinner} role="status" aria-label="Инструмент выполняется" />
        ) : (
          <Check size={15} className={styles.check} />
        )}
        <ChevronRight size={15} className={cx(styles.chevron, open && styles.chevronOpen)} />
      </button>
      {open && (
        <div className={styles.body}>
          <div className={styles.field}>
            <span className={styles.fieldLabel}>Запрос:</span>
            <span className={styles.value}>{formatArgs(args)}</span>
          </div>
          {!running && (
            <div className={styles.field}>
              <span className={styles.fieldLabel}>Результат:</span>
              <span className={styles.value}>{resultText}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
