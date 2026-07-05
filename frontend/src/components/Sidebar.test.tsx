import { render, screen } from '@testing-library/react'
import { AuthProvider } from '../auth/AuthContext'
import { Sidebar } from './Sidebar'

beforeEach(() =>
  localStorage.setItem('capybara.session', JSON.stringify({ token: 't', username: 'roman' })),
)

test('deferred nav items are disabled; Память is an enabled button', () => {
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
        onOpenMemory={() => {}}
        memoryActive={false}
      />
    </AuthProvider>,
  )
  // «Фоновые задачи» and «Настройки» remain disabled placeholders.
  for (const label of ['Фоновые задачи', 'Настройки']) {
    expect(screen.getByText(label).closest('[aria-disabled="true"]')).not.toBeNull()
  }
  // «Память» is now an enabled button.
  expect(screen.getByRole('button', { name: 'Память' })).toBeInTheDocument()
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
        onOpenMemory={() => {}}
        memoryActive={false}
      />
    </AuthProvider>,
  )
  expect(screen.getByText('Избранное')).toBeInTheDocument()
  const fav = screen.getByText('Звёздный')
  const normal = screen.getByText('Обычный')
  expect(fav.compareDocumentPosition(normal) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})
