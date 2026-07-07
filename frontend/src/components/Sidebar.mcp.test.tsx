import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AuthProvider } from '../auth/AuthContext'
import { Sidebar } from './Sidebar'

function noop() {}

function renderSidebar(overrides: Partial<Parameters<typeof Sidebar>[0]> = {}) {
  return render(
    <AuthProvider>
      <Sidebar
        chats={[]}
        activeChatId={null}
        collapsed={false}
        onToggleCollapse={noop}
        onSelect={noop}
        onNewChat={noop}
        onToggleFavorite={noop}
        onRename={noop}
        onDelete={noop}
        onOpenMemory={noop}
        memoryActive={false}
        onOpenMcp={noop}
        mcpActive={false}
        {...overrides}
      />
    </AuthProvider>,
  )
}

test('renders the MCP nav item and fires onOpenMcp', async () => {
  const onOpenMcp = vi.fn()
  renderSidebar({ onOpenMcp })
  await userEvent.click(screen.getByRole('button', { name: 'MCP-серверы' }))
  expect(onOpenMcp).toHaveBeenCalled()
})
