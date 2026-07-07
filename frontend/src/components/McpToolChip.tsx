/** A discovered MCP tool: mono name with an enable/disable checkbox toggle. */
import type { McpToolOut } from '../api/types'
import styles from './McpToolChip.module.css'

export function McpToolChip({
  tool,
  onToggle,
}: {
  tool: McpToolOut
  onToggle: (enabled: boolean) => void
}) {
  return (
    <label
      className={tool.enabled ? styles.chip : `${styles.chip} ${styles.disabled}`}
      title={tool.description ?? undefined}
    >
      <input
        type="checkbox"
        className={styles.toggle}
        checked={tool.enabled}
        onChange={(e) => onToggle(e.target.checked)}
        aria-label={`Инструмент ${tool.name}`}
      />
      {tool.name}
    </label>
  )
}
