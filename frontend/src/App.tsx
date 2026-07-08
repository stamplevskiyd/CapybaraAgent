import { AuthProvider, useAuth } from './auth/AuthContext'
import { AuthScreen } from './screens/AuthScreen'
import { ChatScreen } from './screens/ChatScreen'
import { BackgroundGlow } from './components/BackgroundGlow'
import { CapybaraChainlitProvider } from './chainlit/ChainlitProvider'
import styles from './App.module.css'

function Router() {
  const { token } = useAuth()
  return (
    <div className={styles.app}>
      <BackgroundGlow />
      {token ? <ChatScreen /> : <AuthScreen />}
    </div>
  )
}

/** App root: wallpaper + auth-gated view. */
export default function App() {
  return (
    <AuthProvider>
      <CapybaraChainlitProvider>
        <Router />
      </CapybaraChainlitProvider>
    </AuthProvider>
  )
}
