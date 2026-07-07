/** Standalone «MCP-серверы» screen: info banner, connect wizard, and server cards. */
import { useState } from 'react'
import { Plug } from 'lucide-react'
import { McpServerCard } from '../components/McpServerCard'
import { ConnectWizard } from '../components/ConnectWizard'
import { pluralServers } from '../components/plural'
import { useMcpServers } from '../mcp/useMcpServers'
import styles from './McpScreen.module.css'

export function McpScreen() {
  const { servers, loading, connect, toggleServer, removeServer, refresh, toggleTool } =
    useMcpServers()
  const [wizardOpen, setWizardOpen] = useState(false)

  return (
    <div className={styles.screen}>
      <div className={styles.inner}>
        <div className={styles.header}>
          <div>
            <h2 className={styles.title}>MCP-серверы</h2>
            <p className={styles.subtitle}>
              {servers.length} {pluralServers(servers.length)} подключено.
            </p>
          </div>
          <button type="button" className={styles.connectBtn} onClick={() => setWizardOpen(true)}>
            <Plug size={15} /> Подключить
          </button>
        </div>

        <div className={styles.banner}>
          Агент может подключать серверы сам — попросите его в чате.
        </div>

        {loading ? (
          <p className={styles.muted}>Загрузка…</p>
        ) : servers.length === 0 ? (
          <p className={styles.muted}>Пока нет подключённых серверов.</p>
        ) : (
          <div className={styles.list}>
            {servers.map((s) => (
              <McpServerCard
                key={s.id}
                server={s}
                onToggle={(enabled) => void toggleServer(s.id, enabled)}
                onRefresh={() => refresh(s.id)}
                onDelete={() => void removeServer(s.id)}
                onToggleTool={(toolId, enabled) => void toggleTool(s.id, toolId, enabled)}
              />
            ))}
          </div>
        )}
      </div>

      {wizardOpen && (
        <ConnectWizard onConnect={connect} onClose={() => setWizardOpen(false)} />
      )}
    </div>
  )
}
