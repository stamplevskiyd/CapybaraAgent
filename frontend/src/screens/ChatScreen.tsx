/** Chat screen: welcome empty-state when no thread is active, or the active thread. */
import { useEffect, useState } from 'react'
import { PanelLeft } from 'lucide-react'
import { AssistantRuntimeProvider } from '@assistant-ui/react'
import { CapyLogo } from '../components/CapyLogo'
import { Composer } from '../components/Composer'
import { Thread } from '../components/Thread'
import { Sidebar } from '../components/Sidebar'
import { MemoryScreen } from './MemoryScreen'
import { McpScreen } from './McpScreen'
import { useAuth, useApiClient } from '../auth/AuthContext'
import { useThreads } from '../chat/useThreads'
import { useModels } from '../chat/useModels'
import { useChainlitThread } from '../chainlit/useChainlitThread'
import { useChatRuntime } from '../chat/runtime'
import { chainlitClient } from '../chainlit/client'
import { deleteChatSettings, putChatSettings } from '../chat/chatSettings'
import {
  loadLastModel,
  saveLastModel,
  loadLastMode,
  saveLastMode,
  loadSidebarCollapsed,
  saveSidebarCollapsed,
} from '../localPrefs'
import { cx } from '../cx'
import type { AgentMode } from '../chat/messages'
import type { ChatOut } from '../api/types'
import styles from './ChatScreen.module.css'

/**
 * Top-level chat layout: sidebar + main area.
 *
 * Chainlit owns threads and messages. The sidebar lists persisted threads merged with
 * per-thread prefs (favorite, model); selecting one resumes it over the socket; «new chat»
 * resets the session and the server assigns a thread id with the first message, which
 * `threadId` then reports back. Favorite and model changes persist to `/chat-settings`;
 * rename/delete go to Chainlit directly.
 */
export function ChatScreen() {
  const { user } = useAuth()
  const api = useApiClient()
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null)
  const [draftModel, setDraftModel] = useState<string | null>(loadLastModel)
  const [draftMode, setDraftMode] = useState<AgentMode>(loadLastMode)
  const [view, setView] = useState<'chat' | 'memory' | 'mcp'>('chat')
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(loadSidebarCollapsed)

  /** Toggle the sidebar open/shut and remember the choice across sessions. */
  function toggleSidebar() {
    setSidebarCollapsed((v) => {
      const next = !v
      saveSidebarCollapsed(next)
      return next
    })
  }

  const { chats, reload, patchLocal, removeLocal } = useThreads()
  const { models } = useModels()
  const { messages, threadId, connected, sending, send, openThread, newThread, cancel } =
    useChainlitThread()

  // The initial thread fetch can race Chainlit's header auth; re-sync once connected.
  useEffect(() => {
    if (connected) void reload()
  }, [connected, reload])

  // Adopt the server-assigned thread id once the first message of a fresh chat exists.
  // Persist the model that was used (until now it only lived in the draft + message
  // metadata) so the thread remembers it across reloads, then refresh the sidebar.
  useEffect(() => {
    if (activeThreadId === null && threadId && messages.length > 0) {
      const newId = threadId
      setActiveThreadId(newId)
      void (async () => {
        if (draftModel) {
          await putChatSettings(api, newId, {
            is_favorite: false,
            model: draftModel,
            mode: draftMode,
          }).catch(() => undefined)
        }
        await reload()
      })()
    }
  }, [activeThreadId, threadId, messages.length, reload, api, draftModel, draftMode])

  const activeChat = chats.find((c) => c.id === activeThreadId)
  const selectedModel = activeChat?.model ?? draftModel
  const selectedMode = activeChat?.mode ?? draftMode

  /**
   * Send a message with the selected model + mode riding in its metadata.
   * No-ops when no valid model is selected OR the chat transport is not connected yet —
   * this guards the Enter path (the composer's disabled Send button does not block Enter),
   * so a message is never emitted into a not-yet-ready socket and silently lost.
   */
  async function handleSend(text: string) {
    const modelValid = selectedModel !== null && models.includes(selectedModel)
    if (!modelValid || !connected) return
    await send(text, selectedModel, selectedMode)
  }

  const runtime = useChatRuntime({
    messages,
    isRunning: sending,
    onSend: handleSend,
    onReload: async () => {},
    onCancel: cancel,
  })

  /**
   * Persist a partial chat-settings change: optimistic local patch, then a full-record PUT
   * (the endpoint replaces the row, so untouched fields are merged from the current chat).
   * A failed save re-syncs the list from the server so the UI never drifts.
   */
  async function persistChatSettings(
    id: string,
    patch: Partial<Pick<ChatOut, 'is_favorite' | 'model' | 'mode'>>,
  ) {
    const chat = chats.find((c) => c.id === id)
    patchLocal(id, patch)
    try {
      await putChatSettings(api, id, {
        is_favorite: patch.is_favorite ?? chat?.is_favorite ?? false,
        model: patch.model !== undefined ? patch.model : (chat?.model ?? null),
        mode: patch.mode ?? chat?.mode ?? 'fast',
      })
    } catch {
      await reload()
    }
  }

  /** Toggle favorite (optimistic; re-syncs on failure). */
  async function handleToggleFavorite(id: string) {
    const chat = chats.find((c) => c.id === id)
    await persistChatSettings(id, { is_favorite: !(chat?.is_favorite ?? false) })
  }

  /** Rename: optimistic local update, then persist to Chainlit; re-sync on failure. */
  async function handleRename(id: string, title: string) {
    patchLocal(id, { title })
    try {
      await chainlitClient.renameThread(id, title)
    } catch {
      await reload()
    }
  }

  /**
   * Delete: remove locally (returning to welcome if it was active), then delete the
   * Chainlit thread and its pref. On failure the list is re-synced from the server.
   */
  async function handleDelete(id: string) {
    if (id === activeThreadId) {
      setActiveThreadId(null)
      newThread()
    }
    removeLocal(id)
    try {
      await chainlitClient.deleteThread(id)
      // The pref is a soft reference; it being gone already is fine.
      await deleteChatSettings(api, id).catch(() => undefined)
    } catch {
      await reload()
    }
  }

  /** Update the selected model: remember it, update the draft, and save the open thread. */
  async function handleSelectModel(model: string) {
    saveLastModel(model)
    setDraftModel(model)
    if (activeThreadId) await persistChatSettings(activeThreadId, { model })
  }

  /** Update the selected agent mode: remember it, update the draft, and save the open thread. */
  async function handleSelectMode(mode: AgentMode) {
    saveLastMode(mode)
    setDraftMode(mode)
    if (activeThreadId) await persistChatSettings(activeThreadId, { mode })
  }

  /** Open a persisted thread: resume its session and show the chat view. */
  function handleSelectThread(id: string) {
    if (id !== activeThreadId) {
      setActiveThreadId(id)
      openThread(id)
    }
    setView('chat')
  }

  /** Start a fresh chat: reset the session and return to the welcome state. */
  function handleNewChat() {
    if (activeThreadId !== null) {
      setActiveThreadId(null)
      newThread()
    }
    setView('chat')
  }

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className={styles.screen}>
        <Sidebar
          chats={chats}
          activeChatId={activeThreadId}
          collapsed={sidebarCollapsed}
          onToggleCollapse={toggleSidebar}
          onSelect={handleSelectThread}
          onNewChat={handleNewChat}
          onToggleFavorite={handleToggleFavorite}
          onRename={handleRename}
          onDelete={handleDelete}
          onOpenMemory={() => setView('memory')}
          memoryActive={view === 'memory'}
          onOpenMcp={() => setView('mcp')}
          mcpActive={view === 'mcp'}
        />
        <main className={styles.main}>
          {sidebarCollapsed && (
            <button
              type="button"
              className={styles.expandBtn}
              onClick={toggleSidebar}
              aria-label="Развернуть панель"
            >
              <PanelLeft size={18} strokeWidth={1.8} />
            </button>
          )}
          {view === 'memory' ? (
            <MemoryScreen />
          ) : view === 'mcp' ? (
            <McpScreen />
          ) : activeThreadId === null && messages.length === 0 ? (
            <div className={styles.welcome}>
              <div className={styles.welcomeContent}>
                <CapyLogo size={64} />
                <h1 className={styles.greeting}>
                  Чем помочь, {user?.displayName ?? 'пользователь'}?
                </h1>
                <p className={styles.subtitle}>Задайте любой вопрос — я помогу.</p>
                <Composer
                  models={models}
                  selectedModel={selectedModel}
                  onSelectModel={handleSelectModel}
                  selectedMode={selectedMode}
                  onSelectMode={handleSelectMode}
                  ready={connected}
                />
              </div>
            </div>
          ) : (
            <div className={styles.active}>
              <header className={cx(styles.header, sidebarCollapsed && styles.headerShifted)}>
                <span className={styles.chatTitle}>{activeChat?.title ?? 'Чат'}</span>
              </header>
              <Thread />
              <div className={styles.composerArea}>
                <div className={styles.composerMaxWidth}>
                  <Composer
                    models={models}
                    selectedModel={selectedModel}
                    onSelectModel={handleSelectModel}
                    selectedMode={selectedMode}
                    onSelectMode={handleSelectMode}
                    ready={connected}
                  />
                </div>
              </div>
            </div>
          )}
        </main>
      </div>
    </AssistantRuntimeProvider>
  )
}
