import { render, screen } from '@testing-library/react'
import { AuthProvider } from '../auth/AuthContext'
import { Sidebar } from './Sidebar'

beforeEach(() =>
  localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'roman' })),
)

test('deferred nav items are disabled', () => {
  render(
    <AuthProvider>
      <Sidebar
        chats={[]}
        activeChatId={null}
        collapsed={false}
        onToggleCollapse={() => {}}
        onSelect={() => {}}
        onNewChat={() => {}}
        onToggleFavorite={() => {}}
        onRename={() => {}}
        onDelete={() => {}}
      />
    </AuthProvider>,
  )
  for (const label of ['Память', 'Фоновые задачи', 'Настройки']) {
    expect(screen.getByText(label).closest('[aria-disabled="true"]')).not.toBeNull()
  }
})

test('favorites appear under an Избранное group above date groups', () => {
  const now = new Date().toISOString()
  const chats = [
    { id: 'a', title: 'Обычный', model: 'm', is_favorite: false, created_at: now, updated_at: now },
    { id: 'b', title: 'Звёздный', model: 'm', is_favorite: true, created_at: now, updated_at: now },
  ]
  render(
    <AuthProvider>
      <Sidebar
        chats={chats}
        activeChatId={null}
        collapsed={false}
        onToggleCollapse={() => {}}
        onSelect={() => {}}
        onNewChat={() => {}}
        onToggleFavorite={() => {}}
        onRename={() => {}}
        onDelete={() => {}}
      />
    </AuthProvider>,
  )
  expect(screen.getByText('Избранное')).toBeInTheDocument()
  const fav = screen.getByText('Звёздный')
  const normal = screen.getByText('Обычный')
  expect(fav.compareDocumentPosition(normal) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})
