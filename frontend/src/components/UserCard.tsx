/** User card shown at the bottom of the Sidebar. Toggles a logout popover on click. */
import { useState, useRef, useEffect } from 'react'
import { ChevronUp, LogOut } from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import styles from './Sidebar.module.css'

/** Displays the logged-in user avatar, name, and a popover with a logout action. */
export function UserCard() {
  const { user, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function handleMouseDown(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleMouseDown)
    return () => {
      document.removeEventListener('mousedown', handleMouseDown)
    }
  }, [open])

  if (!user) return null

  const initial = (user.displayName || user.username).charAt(0).toUpperCase()

  return (
    <div ref={wrapRef} className={styles.userCardWrap}>
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
          style={{
            transform: open ? 'rotate(0deg)' : 'rotate(180deg)',
            transition: 'transform 0.15s ease',
          }}
        />
      </button>
    </div>
  )
}
