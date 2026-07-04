import { describe, expect, test, vi } from 'vitest'
import { deleteChat, renameChat, setFavorite } from './chatApi'
import type { ApiClient } from '../api/client'

function fakeApi() {
  return {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn().mockResolvedValue({ id: 'c1' }),
    del: vi.fn().mockResolvedValue(undefined),
    stream: vi.fn(),
  } as unknown as ApiClient & Record<string, ReturnType<typeof vi.fn>>
}

describe('chat mutation calls', () => {
  test('deleteChat DELETEs the chat', async () => {
    const api = fakeApi()
    await deleteChat(api, 'c1')
    expect(api.del).toHaveBeenCalledWith('/chats/c1')
  })
  test('renameChat PATCHes title', async () => {
    const api = fakeApi()
    await renameChat(api, 'c1', 'Новое имя')
    expect(api.patch).toHaveBeenCalledWith('/chats/c1', { title: 'Новое имя' })
  })
  test('setFavorite PATCHes is_favorite', async () => {
    const api = fakeApi()
    await setFavorite(api, 'c1', true)
    expect(api.patch).toHaveBeenCalledWith('/chats/c1', { is_favorite: true })
  })
})
