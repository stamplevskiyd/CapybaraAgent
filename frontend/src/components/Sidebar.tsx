/** Sidebar navigation panel: logo, new-chat button, search, chat list, deferred nav, user card. */
import { useState } from 'react'
import { Plus, Search, Brain, Clock, Settings } from 'lucide-react'
import { CapyLogo } from './CapyLogo'
import { ChatListItem } from './ChatListItem'
import { UserCard } from './UserCard'
import type { ChatOut } from '../api/types'
import styles from './Sidebar.module.css'

/** Groups chats into today / yesterday / earlier buckets based on `created_at`. */
function groupChats(chats: ChatOut[]): { label: string; items: ChatOut[] }[] {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const yesterday = new Date(today)
  yesterday.setDate(today.getDate() - 1)

  const todayItems: ChatOut[] = []
  const yesterdayItems: ChatOut[] = []
  const earlierItems: ChatOut[] = []

  for (const chat of chats) {
    const d = new Date(chat.created_at)
    const chatDay = new Date(d.getFullYear(), d.getMonth(), d.getDate())
    if (chatDay >= today) {
      todayItems.push(chat)
    } else if (chatDay >= yesterday) {
      yesterdayItems.push(chat)
    } else {
      earlierItems.push(chat)
    }
  }

  const groups: { label: string; items: ChatOut[] }[] = []
  if (todayItems.length) groups.push({ label: 'Сегодня', items: todayItems })
  if (yesterdayItems.length) groups.push({ label: 'Вчера', items: yesterdayItems })
  if (earlierItems.length) groups.push({ label: 'Ранее', items: earlierItems })
  return groups
}

/** Full sidebar: logo lockup, new-chat, search filter, grouped chat list, disabled deferred nav, user card. */
export function Sidebar({
  chats,
  activeChatId,
  onSelect,
  onNewChat,
}: {
  chats: ChatOut[]
  activeChatId: string | null
  onSelect: (id: string) => void
  onNewChat: () => void
}) {
  const [query, setQuery] = useState('')

  const filtered = query
    ? chats.filter((c) => c.title.toLowerCase().includes(query.toLowerCase()))
    : chats

  const groups = groupChats(filtered)

  return (
    <aside className={styles.sidebar}>
      <div className={styles.logoBlock}>
        <CapyLogo size={40} />
        <div className={styles.logoText}>
          <span className={styles.logoName}>CapybaraAgent</span>
          <span className={styles.logoSub}>локальный агент</span>
        </div>
      </div>

      <button type="button" className={styles.newChatBtn} onClick={onNewChat}>
        <span className={styles.newChatIcon}>
          <Plus size={16} />
        </span>
        Новый чат
      </button>

      <div className={styles.searchWrap}>
        <span className={styles.searchIcon}>
          <Search size={14} />
        </span>
        <input
          type="text"
          className={styles.searchInput}
          placeholder="Поиск…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      <div className={styles.chatList}>
        {groups.map((group) => (
          <div key={group.label}>
            <div className={styles.groupLabel}>{group.label}</div>
            {group.items.map((chat) => (
              <ChatListItem
                key={chat.id}
                chat={chat}
                active={chat.id === activeChatId}
                onSelect={() => onSelect(chat.id)}
              />
            ))}
          </div>
        ))}
      </div>

      <div className={styles.bottomBlock}>
        <div aria-disabled="true" className={styles.navDisabled}>
          <Brain size={16} />
          Память
        </div>
        <div aria-disabled="true" className={styles.navDisabled}>
          <Clock size={16} />
          Фоновые задачи
          <span className={styles.badge}>2</span>
        </div>
        <div aria-disabled="true" className={styles.navDisabled}>
          <Settings size={16} />
          Настройки
        </div>
        <UserCard />
      </div>
    </aside>
  )
}
