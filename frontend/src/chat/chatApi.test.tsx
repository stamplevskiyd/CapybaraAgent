import { describe, expect, test, vi } from 'vitest'
import { createChat, listModels, patchChatModel } from './chatApi'
import type { ApiClient } from '../api/client'

function fakeApi(): ApiClient & { get: ReturnType<typeof vi.fn>; post: ReturnType<typeof vi.fn>; patch: ReturnType<typeof vi.fn> } {
  return {
    get: vi.fn().mockResolvedValue({ provider: 'ollama', models: ['llama3.1:8b'] }),
    post: vi.fn().mockResolvedValue({ id: 'c1' }),
    patch: vi.fn().mockResolvedValue({ id: 'c1', model: 'llama3.1:8b' }),
    stream: vi.fn(),
  } as never
}

describe('chatApi model calls', () => {
  test('listModels GETs /models', async () => {
    const api = fakeApi()
    const out = await listModels(api)
    expect(api.get).toHaveBeenCalledWith('/models')
    expect(out.models).toEqual(['llama3.1:8b'])
  })

  test('createChat sends title and model', async () => {
    const api = fakeApi()
    await createChat(api, 'Hi', 'llama3.1:8b')
    expect(api.post).toHaveBeenCalledWith('/chats', { title: 'Hi', model: 'llama3.1:8b' })
  })

  test('patchChatModel PATCHes the chat', async () => {
    const api = fakeApi()
    await patchChatModel(api, 'c1', 'llama3.1:8b')
    expect(api.patch).toHaveBeenCalledWith('/chats/c1', { model: 'llama3.1:8b' })
  })
})
