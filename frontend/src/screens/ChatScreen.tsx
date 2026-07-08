/** Chat screen: welcome empty-state when no chat is active, or active thread with streaming. */
import { useEffect, useRef, useState } from 'react'
import { PanelLeft } from 'lucide-react'
import { AssistantRuntimeProvider } from '@assistant-ui/react'
import { CapyLogo } from '../components/CapyLogo'
import { Composer } from '../components/Composer'
import { Thread } from '../components/Thread'
import { Sidebar } from '../components/Sidebar'
import { MemoryScreen } from './MemoryScreen'
import { McpScreen } from './McpScreen'
import { useAuth, useApiClient } from '../auth/AuthContext'
import { useChats } from '../chat/useChats'
import { useModels } from '../chat/useModels'
import { useChainlitThread } from '../chainlit/useChainlitThread'
import { useChatRuntime } from '../chat/runtime'
import { deleteChat, renameChat, setFavorite, patchChatModel } from '../chat/chatApi'
import { loadLastModel, saveLastModel } from '../chat/lastModel'
import styles from './ChatScreen.module.css'

/**
 * Top-level chat layout: sidebar + main area.
 *
 * When `activeChatId` is null renders the welcome state (glyph, greeting, composer).
 * When set renders the active thread (header, Thread, loading indicator, composer).
 *
 * The whole screen is wrapped in `AssistantRuntimeProvider` so both the welcome
 * Composer and the active Thread share one runtime (send, cancel, reload all flow through it).
 *
 * Send flow for a new chat:
 *   1. `newChat()` creates the chat and returns its id.
 *   2. `setActiveChatId(id)` is called; `skipLoadHistory.current` is set to true.
 *   3. `send(text, id)` is called with the chatId override so no deferral is needed.
 *   4. `skipLoadHistory` prevents `loadHistory` from being called for the new chat
 *      (it has no server-side history yet; messages come from the live stream).
 */
export function ChatScreen() {
  const { user } = useAuth()
  const api = useApiClient()
  const [activeChatId, setActiveChatId] = useState<string | null>(null)
  const [draftModel, setDraftModel] = useState<string | null>(() => loadLastModel())
  const [view, setView] = useState<'chat' | 'memory' | 'mcp'>('chat')
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem('capybara.sidebarCollapsed') === '1'
    } catch {
      return false
    }
  })
  /** Set to true before updating activeChatId for a brand-new chat to skip history load. */
  const skipLoadHistory = useRef(false)

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

  const { chats, reload, newChat, patchLocal, removeLocal } = useChats()
  const { models } = useModels()
  const { messages, sending, loadingHistory, send, loadHistory, cancel, regenerate } =
    useChainlitThread()

  /**
   * Load history whenever the active chat changes.
   * Skipped for newly created chats (they are empty; messages come from the live stream).
   */
  useEffect(() => {
    if (skipLoadHistory.current) {
      skipLoadHistory.current = false
      return
    }
    void loadHistory()
  }, [loadHistory])

  const activeChat = chats.find((c) => c.id === activeChatId)
  const selectedModel = activeChatId ? (activeChat?.model ?? null) : draftModel

  /**
   * Send a message.
   * If no chat is active, creates one first and sends with the chatId override (no deferral).
   * If a chat is already active, sends immediately.
   * No-ops when no valid model is selected — guards the Enter path as well as the button.
   */
  async function handleSend(text: string) {
    const modelValid = selectedModel !== null && models.includes(selectedModel)
    if (!modelValid) return
    if (activeChatId) {
      // No reload: Chainlit streams the reply into the active thread state.
      await send(text)
      return
    }
    const chat = await newChat(draftModel ?? undefined)
    setActiveChatId(chat.id)
    skipLoadHistory.current = true
    await send(text, chat.id)
  }

  const runtime = useChatRuntime({
    messages,
    isRunning: sending,
    onSend: handleSend,
    onReload: regenerate,
    onCancel: cancel,
  })

  /**
   * Toggle favorite: optimistic local flip, then persist. On failure the list is
   * re-synced from the server so the UI never drifts from the persisted state.
   */
  async function handleToggleFavorite(id: string) {
    const chat = chats.find((c) => c.id === id)
    const next = !(chat?.is_favorite ?? false)
    patchLocal(id, { is_favorite: next })
    try {
      await setFavorite(api, id, next)
    } catch {
      await reload()
    }
  }

  /** Rename: optimistic local update, then persist; re-sync from the server on failure. */
  async function handleRename(id: string, title: string) {
    patchLocal(id, { title })
    try {
      await renameChat(api, id, title)
    } catch {
      await reload()
    }
  }

  /**
   * Delete: remove locally (returning to welcome if it was active), then persist.
   * On failure the still-existing chat is restored via a re-sync, and re-selected
   * if it was the active one.
   */
  async function handleDelete(id: string) {
    const wasActive = id === activeChatId
    if (wasActive) setActiveChatId(null)
    removeLocal(id)
    try {
      await deleteChat(api, id)
    } catch {
      await reload()
      if (wasActive) setActiveChatId(id)
    }
  }

  /**
   * Update the selected model; persists to localStorage, updates draft, and PATCHes
   * the active chat if open. A failed PATCH reverts the draft and re-syncs the chat.
   */
  async function handleSelectModel(model: string) {
    const prevDraft = draftModel
    saveLastModel(model)
    setDraftModel(model)
    if (activeChatId) {
      try {
        await patchChatModel(api, activeChatId, model)
        await reload()
      } catch {
        setDraftModel(prevDraft)
        await reload()
      }
    }
  }

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className={styles.screen}>
        <Sidebar
          chats={chats}
          activeChatId={activeChatId}
          collapsed={sidebarCollapsed}
          onToggleCollapse={toggleSidebar}
          onSelect={(id) => {
            setActiveChatId(id)
            setView('chat')
          }}
          onNewChat={() => {
            setActiveChatId(null)
            setView('chat')
          }}
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
          ) : activeChatId === null ? (
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
              {loadingHistory && messages.length === 0 ? (
                <div className={styles.loading} role="status">
                  Загрузка…
                </div>
              ) : (
                <Thread />
              )}
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
