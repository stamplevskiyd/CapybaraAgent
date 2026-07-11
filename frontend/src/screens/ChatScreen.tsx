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
import { deleteChatPref, putChatPref } from '../chat/chatPrefs'
import { loadLastModel, saveLastModel } from '../chat/lastModel'
import styles from './ChatScreen.module.css'

/**
 * Top-level chat layout: sidebar + main area.
 *
 * Chainlit owns threads and messages. The sidebar lists persisted threads merged with
 * per-thread prefs (favorite, model); selecting one resumes it over the socket; «new chat»
 * resets the session and the server assigns a thread id with the first message, which
 * `threadId` then reports back. Favorite and model changes persist to `/chat-prefs`;
 * rename/delete go to Chainlit directly.
 */
export function ChatScreen() {
  const { user } = useAuth()
  const api = useApiClient()
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null)
  const [draftModel, setDraftModel] = useState<string | null>(() => loadLastModel())
  const [view, setView] = useState<'chat' | 'memory' | 'mcp'>('chat')
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem('capybara.sidebarCollapsed') === '1'
    } catch {
      return false
    }
  })

  /** Toggle the sidebar open/shut and remember the choice across sessions. */
  function toggleSidebar() {
    setSidebarCollapsed((v) => {
      const next = !v
      try {
        localStorage.setItem('capybara.sidebarCollapsed', next ? '1' : '0')
      } catch {
        // ignore storage failures — collapse state is a convenience
      }
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
          await putChatPref(api, newId, { is_favorite: false, model: draftModel }).catch(
            () => undefined,
          )
        }
        await reload()
      })()
    }
  }, [activeThreadId, threadId, messages.length, reload, api, draftModel])

  const activeChat = chats.find((c) => c.id === activeThreadId)
  const selectedModel = activeChat?.model ?? draftModel

  /**
   * Send a message with the selected model riding in its metadata.
   * No-ops when no valid model is selected — guards the Enter path as well as the button.
   */
  async function handleSend(text: string) {
    const modelValid = selectedModel !== null && models.includes(selectedModel)
    if (!modelValid) return
    await send(text, selectedModel)
  }

  const runtime = useChatRuntime({
    messages,
    isRunning: sending,
    onSend: handleSend,
    onReload: async () => {},
    onCancel: cancel,
  })

  /**
   * Toggle favorite: optimistic local flip, then persist to chat-prefs. On failure the
   * list is re-synced from the server so the UI never drifts from the persisted state.
   */
  async function handleToggleFavorite(id: string) {
    const chat = chats.find((c) => c.id === id)
    const next = !(chat?.is_favorite ?? false)
    patchLocal(id, { is_favorite: next })
    try {
      await putChatPref(api, id, { is_favorite: next, model: chat?.model ?? null })
    } catch {
      await reload()
    }
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
      await deleteChatPref(api, id).catch(() => undefined)
    } catch {
      await reload()
    }
  }

  /**
   * Update the selected model; persists to localStorage, updates the draft, and saves
   * the active thread's pref if one is open. A failed save re-syncs from the server.
   */
  async function handleSelectModel(model: string) {
    saveLastModel(model)
    setDraftModel(model)
    if (activeThreadId) {
      const wasFavorite = activeChat?.is_favorite ?? false
      patchLocal(activeThreadId, { model })
      try {
        await putChatPref(api, activeThreadId, { is_favorite: wasFavorite, model })
      } catch {
        await reload()
      }
    }
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
                />
              </div>
            </div>
          ) : (
            <div className={styles.active}>
              <header
                className={
                  sidebarCollapsed ? `${styles.header} ${styles.headerShifted}` : styles.header
                }
              >
                <span className={styles.chatTitle}>{activeChat?.title ?? 'Чат'}</span>
              </header>
              <Thread />
              <div className={styles.composerArea}>
                <div className={styles.composerMaxWidth}>
                  <Composer
                    models={models}
                    selectedModel={selectedModel}
                    onSelectModel={handleSelectModel}
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
