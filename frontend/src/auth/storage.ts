const KEY = 'capybara.session'
export type Session = { token: string; username: string; displayName?: string }

export function loadSession(): Session | null {
  const raw = localStorage.getItem(KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as Session
  } catch {
    return null
  }
}
export function saveSession(s: Session): void {
  localStorage.setItem(KEY, JSON.stringify(s))
}
export function clearSession(): void {
  localStorage.removeItem(KEY)
}
