import { render, screen } from '@testing-library/react'
import { AuthProvider } from '../auth/AuthContext'
import { Sidebar } from './Sidebar'

beforeEach(() =>
  localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'roman' })),
)

test('deferred nav items are disabled', () => {
  render(
    <AuthProvider>
      <Sidebar chats={[]} activeChatId={null} onSelect={() => {}} onNewChat={() => {}} />
    </AuthProvider>,
  )
  for (const label of ['Память', 'Фоновые задачи', 'Настройки']) {
    expect(screen.getByText(label).closest('[aria-disabled="true"]')).not.toBeNull()
  }
})
