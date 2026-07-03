import { AuthProvider, useAuth } from './auth/AuthContext'
import { AuthScreen } from './screens/AuthScreen'
import { BackgroundGlow } from './components/BackgroundGlow'
import styles from './App.module.css'

function Router() {
  const { token } = useAuth()
  return (
    <div className={styles.app}>
      <BackgroundGlow />
      {token ? <div>chat</div> : <AuthScreen />}
    </div>
  )
}

/** App root: wallpaper + auth-gated view. */
export default function App() {
  return (
    <AuthProvider>
      <Router />
    </AuthProvider>
  )
}
