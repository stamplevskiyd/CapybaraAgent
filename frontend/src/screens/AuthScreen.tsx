import { useState, type FormEvent } from 'react'
import { Lock } from 'lucide-react'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { CapyLogo } from '../components/CapyLogo'
import styles from './AuthScreen.module.css'

/** Full-screen login/register card shown while logged out. */
export function AuthScreen() {
  const { login, register } = useAuth()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [displayName, setDisplayName] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      if (mode === 'login') await login(username, password)
      else await register(displayName, username, password)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401)
        setError('Неверный логин или пароль')
      else if (err instanceof ApiError && err.status === 409)
        setError('Логин уже занят')
      else setError('Что-то пошло не так. Попробуйте ещё раз.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={styles.screen}>
      <div className={styles.header}>
        <CapyLogo size={60} />
        <div className={styles.wordmark}>CapybaraAgent</div>
        <div className={styles.tagline}>Локальный AI-агент</div>
      </div>
      <form className={styles.card} onSubmit={onSubmit}>
        <h1 className={styles.title}>
          {mode === 'login' ? 'С возвращением' : 'Создать пользователя'}
        </h1>
        <p className={styles.subtitle}>
          {mode === 'login'
            ? 'Войдите в свой локальный профиль.'
            : 'Профиль хранится только на этом устройстве.'}
        </p>
        {mode === 'register' && (
          <label className={styles.field}>
            <span>Имя</span>
            <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          </label>
        )}
        <label className={styles.field}>
          <span>Логин</span>
          <input value={username} onChange={(e) => setUsername(e.target.value)} />
        </label>
        <label className={styles.field}>
          <span>Пароль</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && <div className={styles.error}>{error}</div>}
        <button className={styles.primary} type="submit" disabled={busy}>
          {mode === 'login' ? 'Войти' : 'Создать аккаунт'}
        </button>
        <div className={styles.switch}>
          {mode === 'login' ? (
            <button type="button" onClick={() => { setMode('register'); setError(null) }}>
              Нет профиля? <span>Создать пользователя</span>
            </button>
          ) : (
            <button type="button" onClick={() => { setMode('login'); setError(null) }}>
              Уже есть профиль? <span>Войти</span>
            </button>
          )}
        </div>
      </form>
      <div className={styles.footer}>
        <Lock size={13} color="#726a61" strokeWidth={1.7} />
        Всё хранится локально на вашем устройстве
      </div>
    </div>
  )
}
