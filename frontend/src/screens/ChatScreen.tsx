/** Chat screen: welcome empty-state when no chat is active, or active thread with streaming. */
import { useEffect, useRef, useState } from 'react'
import { CapyLogo } from '../components/CapyLogo'
import { Composer } from '../components/Composer'
import { Message } from '../components/Message'
import { Sidebar } from '../components/Sidebar'
import { useAuth, useApiClient } from '../auth/AuthContext'
import { useChats } from '../chat/useChats'
import { useModels } from '../chat/useModels'
import { useChatStream } from '../chat/useChatStream'
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
 * When set renders the active thread (header, message list, composer).
 *
 * Send flow for a new chat:
 *   1. `newChat()` creates the chat and returns its id.
 *   2. State is updated: `activeChatId = id`, `pendingSend = text`.
 *   3. On the next render `useChatStream(id)` has the correct `chatId`; the pending-send
 *      effect fires `send(text)` and then `reload()`.
 *
 * This deferred approach is necessary because `useChatStream.send` closes over `chatId` at
 * render time — calling it before the re-render would produce a no-op.
 */
export function ChatScreen() {
  const { user } = useAuth()
  const api = useApiClient()
  const [activeChatId, setActiveChatId] = useState<string | null>(null)
  const [pendingSend, setPendingSend] = useState<string | null>(null)
  const [chipText, setChipText] = useState('')
  const [composerKey, setComposerKey] = useState(0)
  const [draftModel, setDraftModel] = useState<string | null>(() => loadLastModel())
  /** Set to true before updating `activeChatId` for a brand-new chat to skip history load. */
  const skipNextHistory = useRef(false)

  const { chats, reload, newChat } = useChats()
  const { models } = useModels()
  const { messages, sending, send, loadHistory } = useChatStream(activeChatId)

  /**
   * Load history whenever the active chat changes.
   * Skipped for newly created chats (they are empty; the fetch would be wasted and
   * the endpoint is not mocked in unit tests for the creation flow).
   */
  useEffect(() => {
    if (skipNextHistory.current) {
      skipNextHistory.current = false
      return
    }
    void loadHistory()
  }, [loadHistory])

  /**
   * Execute a deferred send after the component re-renders with the new `activeChatId`.
   * Fires only when both `activeChatId` and `pendingSend` are non-null.
   */
  useEffect(() => {
    if (!activeChatId || pendingSend === null) return
    const text = pendingSend
    setPendingSend(null)
    void (async () => {
      await send(text)
      await reload()
    })()
  }, [activeChatId, pendingSend, send, reload])

  /** Update the selected model; persists to localStorage, updates draft, and PATCHes the active chat if open. */
  async function handleSelectModel(model: string) {
    saveLastModel(model)
    setDraftModel(model)
    if (activeChatId) {
      await patchChatModel(api, activeChatId, model)
      await reload()
    }
  }

  /**
   * Send a message.
   * If no chat is active, creates one first; the actual stream is deferred via
   * `pendingSend` so that `useChatStream.send` has the correct `chatId`.
   * If a chat is already active, sends immediately.
   */
  async function handleSend(text: string) {
    let id = activeChatId
    if (!id) {
      const chat = await newChat(draftModel ?? undefined)
      id = chat.id
      skipNextHistory.current = true
      setActiveChatId(id)
      setPendingSend(text)
      return
    }
    await send(text)
    await reload()
  }

  /** Select an existing chat and load its history. */
  function handleSelect(id: string) {
    setActiveChatId(id)
  }

  /** Return to the welcome state; history is cleared via loadHistory's null-branch. */
  function handleNewChat() {
    setActiveChatId(null)
  }

  /** Prefill the composer text via a prompt chip; remount composer to pick up new text. */
  function handleChip(label: string) {
    setChipText(label)
    setComposerKey((k) => k + 1)
  }

  const activeChat = chats.find((c) => c.id === activeChatId)
  const selectedModel = activeChatId ? (activeChat?.model ?? null) : draftModel

  return (
    <div className={styles.screen}>
      <Sidebar
        chats={chats}
        activeChatId={activeChatId}
        onSelect={handleSelect}
        onNewChat={handleNewChat}
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
                key={composerKey}
                onSend={handleSend}
                disabled={sending}
                initialText={chipText}
                models={models}
                selectedModel={selectedModel}
                onSelectModel={handleSelectModel}
              />
              <div className={styles.chips}>
                {CHIPS.map((c) => (
                  <button
                    key={c.label}
                    type="button"
                    className={styles.chip}
                    onClick={() => handleChip(c.label)}
                  >
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
            <div className={styles.thread}>
              <div className={styles.threadInner}>
                {messages.map((msg) => (
                  <Message key={msg.id} message={msg} />
                ))}
              </div>
            </div>
            <div className={styles.composerArea}>
              <div className={styles.composerMaxWidth}>
                <Composer
                  onSend={handleSend}
                  disabled={sending}
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
  )
}
