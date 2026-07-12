/** One attached MCP server: status, url, enable toggle, refresh/delete, tool chips. */
import { useState } from 'react'
import { RotateCw, Trash2 } from 'lucide-react'
import type { McpServerOut } from '../api/types'
import { McpToolChip } from './McpToolChip'
import { pluralTools } from './plural'
import { cx } from '../cx'
import styles from './McpServerCard.module.css'

export function McpServerCard({
  server,
  onToggle,
  onRefresh,
  onDelete,
  onToggleTool,
}: {
  server: McpServerOut
  onToggle: (enabled: boolean) => void
  onRefresh: () => Promise<void>
  onDelete: () => void
  onToggleTool: (toolId: string, enabled: boolean) => void
}) {
  const [refreshing, setRefreshing] = useState(false)
  const ok = server.last_connected_at !== null && server.last_error === null

  async function handleRefresh() {
    setRefreshing(true)
    try {
      await onRefresh()
    } finally {
      setRefreshing(false)
    }
  }

  function handleDelete() {
    if (window.confirm(`Удалить сервер «${server.name}»?`)) onDelete()
  }

  return (
    <div className={styles.card}>
      <div className={styles.head}>
        <span className={cx(styles.dot, ok ? styles.dotOk : styles.dotErr)} aria-hidden="true" />
        <div className={styles.titleBlock}>
          <span className={styles.name}>{server.name}</span>
          <span className={styles.url}>{server.url}</span>
        </div>
        <div className={styles.actions}>
          <label className={styles.switch} aria-label="Сервер включён">
            <input
              type="checkbox"
              checked={server.enabled}
              onChange={(e) => onToggle(e.target.checked)}
            />
          </label>
          <button
            type="button"
            className={styles.iconBtn}
            aria-label="Обновить"
            disabled={refreshing}
            onClick={handleRefresh}
          >
            <RotateCw size={14} className={cx(refreshing && styles.spin)} />
          </button>
          <button
            type="button"
            className={styles.iconBtn}
            aria-label="Удалить сервер"
            onClick={handleDelete}
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {server.last_error !== null && <div className={styles.error}>{server.last_error}</div>}

      <div className={styles.toolCount}>
        {server.tools.length} {pluralTools(server.tools.length)}
      </div>
      <div className={styles.tools}>
        {server.tools.map((t) => (
          <McpToolChip key={t.id} tool={t} onToggle={(enabled) => onToggleTool(t.id, enabled)} />
        ))}
      </div>
    </div>
  )
}
