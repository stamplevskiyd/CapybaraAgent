import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'
import { createApiClient, type ApiClient } from '../api/client'
import type { TokenResponse, UserOut } from '../api/types'
// UserOut is used for both registration and the /users/me profile fetch.
import { clearSession, loadSession, saveSession } from './storage'

type User = { username: string; displayName: string }
type AuthValue = {
  user: User | null
  token: string | null
  login: (username: string, password: string) => Promise<void>
  register: (displayName: string, username: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthValue | null>(null)
const ApiContext = createContext<ApiClient | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const initial = loadSession()
  const [token, setToken] = useState<string | null>(initial?.token ?? null)
  const [user, setUser] = useState<User | null>(
    initial ? { username: initial.username, displayName: initial.displayName ?? initial.username } : null,
  )
  const tokenRef = useRef<string | null>(token)
  tokenRef.current = token

  const logout = useCallback(() => {
    clearSession()
    setToken(null)
    setUser(null)
  }, [])

  const api = useMemo(
    () => createApiClient({ getToken: () => tokenRef.current, onUnauthorized: logout }),
    [logout],
  )

  const login = useCallback(
    async (username: string, password: string) => {
      const res = await api.post<TokenResponse>('/auth/login', { username, password })
      // Make the token available to the immediately-following /users/me request.
      tokenRef.current = res.access_token
      const me = await api.get<UserOut>('/users/me')
      saveSession({ token: res.access_token, username: me.username, displayName: me.display_name })
      setToken(res.access_token)
      setUser({ username: me.username, displayName: me.display_name })
    },
    [api],
  )

  const register = useCallback(
    async (displayName: string, username: string, password: string) => {
      await api.post<UserOut>('/users', {
        display_name: displayName,
        username,
        password,
      })
      await login(username, password)
    },
    [api, login],
  )

  const value = useMemo<AuthValue>(
    () => ({ user, token, login, register, logout }),
    [user, token, login, register, logout],
  )
  return (
    <ApiContext.Provider value={api}>
      <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
    </ApiContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthValue {
  const v = useContext(AuthContext)
  if (!v) throw new Error('useAuth must be used within AuthProvider')
  return v
}
// eslint-disable-next-line react-refresh/only-export-components
export function useApiClient(): ApiClient {
  const v = useContext(ApiContext)
  if (!v) throw new Error('useApiClient must be used within AuthProvider')
  return v
}
