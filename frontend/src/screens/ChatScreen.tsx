/** Chat screen: welcome empty-state when no chat is active, or active thread with streaming. */
import { useEffect, useRef, useState } from 'react'
import { AssistantRuntimeProvider } from '@assistant-ui/react'
import { CapyLogo } from '../components/CapyLogo'
import { Composer } from '../components/Composer'
import { Thread } from '../components/Thread'
import { Sidebar } from '../components/Sidebar'
import { useAuth, useApiClient } from '../auth/AuthContext'
import { useChats } from '../chat/useChats'
import { useModels } from '../chat/useModels'
import { useChatStream } from '../chat/useChatStream'
import { useChatRuntime } from '../chat/runtime'
import { patchChatModel } from '../chat/chatApi'
import { loadLastModel, saveLastModel } from '../chat/lastModel'
import styles from './ChatScreen.module.css'

/** Prompt chips shown on the welcome screen to seed the composer. */
const CHIPS = [
  { emoji: '✍️', label: 'Написать текст' },
  { emoji: '🔍', label: 'Найти информацию' },
  { emoji: '💡', label: 'Придумать идею' },
  { emoji: '📝', label: 'Суммаризировать' },
]

/**
 * Top-level chat layout: sidebar + main area.
 *
 * When `activeChatId` is null renders the welcome state (glyph, greeting, composer, chips).
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
 *
 * Note on welcome chips: `initialText` was removed from Composer, so chips no longer
 * prefill the input. The buttons are kept for visual parity but have no click handler.
 * Chip-to-composer prefill can be wired in a follow-up via the composer runtime API.
 */
export function ChatScreen() {
  const { user } = useAuth()
  const api = useApiClient()
  const [activeChatId, setActiveChatId] = useState<string | null>(null)
  const [draftModel, setDraftModel] = useState<string | null>(() => loadLastModel())
  /** Set to true before updating activeChatId for a brand-new chat to skip history load. */
  const skipLoadHistory = useRef(false)

  const { chats, reload, newChat } = useChats()
  const { models } = useModels()
  const { messages, sending, loadingHistory, send, loadHistory, cancel, regenerate } =
    useChatStream(activeChatId)

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
      await send(text)
      await reload()
      return
    }
    const chat = await newChat(draftModel ?? undefined)
    setActiveChatId(chat.id)
    skipLoadHistory.current = true
    await send(text, chat.id)
    await reload()
  }

  const runtime = useChatRuntime({
    messages,
    isRunning: sending,
    onSend: handleSend,
    onReload: regenerate,
    onCancel: cancel,
  })

  /** Update the selected model; persists to localStorage, updates draft, and PATCHes the active chat if open. */
  async function handleSelectModel(model: string) {
    saveLastModel(model)
    setDraftModel(model)
    if (activeChatId) {
      await patchChatModel(api, activeChatId, model)
      await reload()
    }
  }

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className={styles.screen}>
        <Sidebar
          chats={chats}
          activeChatId={activeChatId}
          onSelect={setActiveChatId}
          onNewChat={() => setActiveChatId(null)}
        />
        <main className={styles.main}>
          {activeChatId === null ? (
            <div className={styles.welcome}>
              <div className={styles.welcomeContent}>
                <CapyLogo size={78} />
                <h1 className={styles.greeting}>
                  Чем помочь, {user?.displayName ?? 'пользователь'}?
                </h1>
                <p className={styles.subtitle}>Задайте вопрос или выберите подсказку ниже.</p>
                <Composer
                  models={models}
                  selectedModel={selectedModel}
                  onSelectModel={handleSelectModel}
                />
                <div className={styles.chips}>
                  {CHIPS.map((c) => (
                    <button key={c.label} type="button" className={styles.chip}>
                      {c.emoji} {c.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className={styles.active}>
              <header className={styles.header}>
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
