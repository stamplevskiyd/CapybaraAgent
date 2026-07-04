import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ChatListItem } from './ChatListItem'
import type { ChatOut } from '../api/types'

const chat: ChatOut = {
  id: 'c1', title: 'Мой чат', model: 'm', is_favorite: false,
  created_at: '', updated_at: '',
}

function noop() {}

test('renders title and toggles favorite', async () => {
  const onToggleFavorite = vi.fn()
  render(
    <ChatListItem chat={chat} active={false} renaming={false} onSelect={noop}
      onToggleFavorite={onToggleFavorite} onOpenMenu={noop}
      onRenameCommit={noop} onRenameCancel={noop} />,
  )
  expect(screen.getByText('Мой чат')).toBeInTheDocument()
  await userEvent.click(screen.getByLabelText('В избранное'))
  expect(onToggleFavorite).toHaveBeenCalled()
})

test('rename mode shows an input that commits on Enter', async () => {
  const onRenameCommit = vi.fn()
  render(
    <ChatListItem chat={chat} active={false} renaming={true} onSelect={noop}
      onToggleFavorite={noop} onOpenMenu={noop}
      onRenameCommit={onRenameCommit} onRenameCancel={noop} />,
  )
  const input = screen.getByRole('textbox')
  await userEvent.clear(input)
  await userEvent.type(input, 'Переименован{Enter}')
  expect(onRenameCommit).toHaveBeenCalledWith('Переименован')
})

test('menu button reports its anchor rect', async () => {
  const onOpenMenu = vi.fn()
  render(
    <ChatListItem chat={chat} active={false} renaming={false} onSelect={noop}
      onToggleFavorite={noop} onOpenMenu={onOpenMenu}
      onRenameCommit={noop} onRenameCancel={noop} />,
  )
  await userEvent.click(screen.getByLabelText('Меню чата'))
  expect(onOpenMenu).toHaveBeenCalled()
})
