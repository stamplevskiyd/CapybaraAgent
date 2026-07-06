import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ChatContextMenu } from './ChatContextMenu'

function noop() {}

test('delete requires a confirm second click', async () => {
  const onDelete = vi.fn()
  render(
    <ChatContextMenu
      x={10}
      y={10}
      isFavorite={false}
      onRename={noop}
      onToggleFavorite={noop}
      onDelete={onDelete}
      onClose={noop}
    />,
  )
  await userEvent.click(screen.getByText('Удалить'))
  expect(onDelete).not.toHaveBeenCalled() // first click arms confirmation
  await userEvent.click(screen.getByText('Точно удалить?'))
  expect(onDelete).toHaveBeenCalled()
})

test('rename fires and shows favorite label based on state', async () => {
  const onRename = vi.fn()
  render(
    <ChatContextMenu
      x={0}
      y={0}
      isFavorite={true}
      onRename={onRename}
      onToggleFavorite={noop}
      onDelete={noop}
      onClose={noop}
    />,
  )
  expect(screen.getByText('Убрать из избранного')).toBeInTheDocument()
  await userEvent.click(screen.getByText('Переименовать'))
  expect(onRename).toHaveBeenCalled()
})
