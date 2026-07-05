/** Sidebar: logo, new-chat, search, favorites + date-grouped chat list, deferred nav, user card. */
import { useState } from 'react'
import { Plus, Search, Brain, Clock, Settings, Star, PanelLeft } from 'lucide-react'
import { CapyLogo } from './CapyLogo'
import { ChatListItem } from './ChatListItem'
import { ChatContextMenu } from './ChatContextMenu'
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
    if (chatDay >= today) todayItems.push(chat)
    else if (chatDay >= yesterday) yesterdayItems.push(chat)
    else earlierItems.push(chat)
  }
  const groups: { label: string; items: ChatOut[] }[] = []
  if (todayItems.length) groups.push({ label: 'Сегодня', items: todayItems })
  if (yesterdayItems.length) groups.push({ label: 'Вчера', items: yesterdayItems })
  if (earlierItems.length) groups.push({ label: 'Ранее', items: earlierItems })
  return groups
}

/** Full sidebar: logo lockup, new-chat, search filter, favorites + date-grouped chat list, disabled deferred nav, user card. */
export function Sidebar({
  chats,
  activeChatId,
  collapsed,
  onToggleCollapse,
  onSelect,
  onNewChat,
  onToggleFavorite,
  onRename,
  onDelete,
}: {
  chats: ChatOut[]
  activeChatId: string | null
  /** When true the sidebar is slid shut (width 0). */
  collapsed: boolean
  /** Toggle collapsed/expanded. */
  onToggleCollapse: () => void
  onSelect: (id: string) => void
  onNewChat: () => void
  onToggleFavorite: (id: string) => void
  onRename: (id: string, title: string) => void
  onDelete: (id: string) => void
}) {
  const [query, setQuery] = useState('')
  const [menu, setMenu] = useState<{ id: string; x: number; y: number } | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)

  const filtered = query
    ? chats.filter((c) => c.title.toLowerCase().includes(query.toLowerCase()))
    : chats
  const favorites = filtered.filter((c) => c.is_favorite)
  const dateGroups = groupChats(filtered.filter((c) => !c.is_favorite))
  const menuChat = menu ? chats.find((c) => c.id === menu.id) : undefined

  const renderItem = (chat: ChatOut) => (
    <ChatListItem
      key={chat.id}
      chat={chat}
      active={chat.id === activeChatId}
      renaming={renamingId === chat.id}
      onSelect={() => onSelect(chat.id)}
      onToggleFavorite={() => onToggleFavorite(chat.id)}
      onOpenMenu={(rect) => setMenu({ id: chat.id, x: rect.left, y: rect.bottom + 4 })}
      onRenameCommit={(title) => {
        setRenamingId(null)
        onRename(chat.id, title)
      }}
      onRenameCancel={() => setRenamingId(null)}
    />
  )

  return (
    <aside
      className={collapsed ? `${styles.sidebar} ${styles.sidebarCollapsed}` : styles.sidebar}
      aria-hidden={collapsed || undefined}
    >
      <div className={styles.sidebarInner}>
        <button
          type="button"
          className={styles.collapseBtn}
          onClick={onToggleCollapse}
          aria-label="Свернуть панель"
        >
          <PanelLeft size={18} strokeWidth={1.8} />
        </button>
        <div className={styles.logoBlock}>
          <div className={styles.logoMark}>
            <CapyLogo size={30} />
          </div>
          <div className={styles.logoText}>
            <span className={styles.logoTitle}>CapybaraAgent</span>
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
            type="search"
            className={styles.searchInput}
            placeholder="Поиск…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Поиск по чатам"
          />
        </div>

        <div className={styles.chatList}>
          {favorites.length > 0 && (
            <div>
              <div className={styles.groupLabel}>
                <Star size={11} fill="currentColor" className={styles.groupStar} /> Избранное
              </div>
              {favorites.map(renderItem)}
            </div>
          )}
          {dateGroups.map((group) => (
            <div key={group.label}>
              <div className={styles.groupLabel}>{group.label}</div>
              {group.items.map(renderItem)}
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

        {menu && menuChat && (
          <ChatContextMenu
            x={menu.x}
            y={menu.y}
            isFavorite={menuChat.is_favorite}
            onRename={() => {
              setRenamingId(menu.id)
              setMenu(null)
            }}
            onToggleFavorite={() => {
              onToggleFavorite(menu.id)
              setMenu(null)
            }}
            onDelete={() => {
              onDelete(menu.id)
              setMenu(null)
            }}
            onClose={() => setMenu(null)}
          />
        )}
      </div>
    </aside>
  )
}
