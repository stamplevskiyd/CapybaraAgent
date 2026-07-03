/** User card shown at the bottom of the Sidebar. Toggles a logout popover on click. */
import { useState } from 'react'
import { ChevronUp, LogOut } from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import styles from './Sidebar.module.css'

/** Displays the logged-in user avatar, name, and a popover with a logout action. */
export function UserCard() {
  const { user, logout } = useAuth()
  const [open, setOpen] = useState(false)

  if (!user) return null

  const initial = (user.displayName || user.username).charAt(0).toUpperCase()

  return (
    <div style={{ position: 'relative' }}>
      {open && (
        <div className={styles.popover}>
          <button
            type="button"
            className={styles.popoverItem}
            onClick={() => {
              setOpen(false)
              logout()
            }}
          >
            <LogOut size={15} />
            Выйти из профиля
          </button>
        </div>
      )}
      <button
        type="button"
        className={styles.userCard}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <div className={styles.userAvatar}>{initial}</div>
        <div className={styles.userInfo}>
          <span className={styles.userName}>{user.displayName || user.username}</span>
          <span className={styles.userSub}>локально</span>
        </div>
        <ChevronUp
          size={14}
          className={styles.userChevron}
          style={{ transform: open ? 'rotate(0deg)' : 'rotate(180deg)', transition: 'transform 0.15s ease' }}
        />
      </button>
    </div>
  )
}
