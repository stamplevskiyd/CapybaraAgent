/** MCP servers state with optimistic mutations reconciled from the server on failure. */
import { useCallback, useEffect, useState } from 'react'
import { useApiClient } from '../auth/AuthContext'
import type { McpServerOut } from '../api/types'
import {
  createServer,
  deleteServer,
  listServers,
  refreshServer,
  setServerEnabled,
  setToolEnabled,
} from './mcpApi'

/**
 * Load and mutate the current user's MCP servers.
 *
 * Card mutations update local state optimistically; on failure the list is
 * re-synced from the server via `reload`. `connect` is wizard-driven: it prepends
 * the created server and rethrows on failure so the wizard can show its error step.
 */
export function useMcpServers() {
  const api = useApiClient()
  const [servers, setServers] = useState<McpServerOut[]>([])
  const [loading, setLoading] = useState(true)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      setServers(await listServers(api))
    } finally {
      setLoading(false)
    }
  }, [api])

  useEffect(() => {
    void reload()
  }, [reload])

  const connect = useCallback(
    async (name: string, url: string, headers: Record<string, string>) => {
      const created = await createServer(api, name, url, headers)
      setServers((prev) => [created, ...prev])
      return created
    },
    [api],
  )

  const toggleServer = useCallback(
    async (id: string, enabled: boolean) => {
      setServers((prev) => prev.map((s) => (s.id === id ? { ...s, enabled } : s)))
      try {
        const updated = await setServerEnabled(api, id, enabled)
        setServers((prev) => prev.map((s) => (s.id === id ? updated : s)))
      } catch {
        await reload()
      }
    },
    [api, reload],
  )

  const removeServer = useCallback(
    async (id: string) => {
      setServers((prev) => prev.filter((s) => s.id !== id))
      try {
        await deleteServer(api, id)
      } catch {
        await reload()
      }
    },
    [api, reload],
  )

  const refresh = useCallback(
    async (id: string) => {
      try {
        const updated = await refreshServer(api, id)
        setServers((prev) => prev.map((s) => (s.id === id ? updated : s)))
      } catch {
        await reload()
      }
    },
    [api, reload],
  )

  const toggleTool = useCallback(
    async (serverId: string, toolId: string, enabled: boolean) => {
      setServers((prev) =>
        prev.map((s) =>
          s.id === serverId
            ? { ...s, tools: s.tools.map((t) => (t.id === toolId ? { ...t, enabled } : t)) }
            : s,
        ),
      )
      try {
        await setToolEnabled(api, serverId, toolId, enabled)
      } catch {
        await reload()
      }
    },
    [api, reload],
  )

  return { servers, loading, reload, connect, toggleServer, removeServer, refresh, toggleTool }
}
