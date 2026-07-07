/** MCP server API calls over the shared authenticated ApiClient. */
import type { ApiClient } from '../api/client'
import type { McpServerOut, McpToolOut } from '../api/types'

export const listServers = (api: ApiClient) => api.get<McpServerOut[]>('/mcp/servers')

export const createServer = (
  api: ApiClient,
  name: string,
  url: string,
  headers: Record<string, string>,
) => api.post<McpServerOut>('/mcp/servers', { name, url, headers })

export const deleteServer = (api: ApiClient, id: string) => api.del(`/mcp/servers/${id}`)

export const refreshServer = (api: ApiClient, id: string) =>
  api.post<McpServerOut>(`/mcp/servers/${id}/refresh`)

export const setServerEnabled = (api: ApiClient, id: string, enabled: boolean) =>
  api.patch<McpServerOut>(`/mcp/servers/${id}`, { enabled })

export const setToolEnabled = (
  api: ApiClient,
  serverId: string,
  toolId: string,
  enabled: boolean,
) => api.patch<McpToolOut>(`/mcp/servers/${serverId}/tools/${toolId}`, { enabled })
