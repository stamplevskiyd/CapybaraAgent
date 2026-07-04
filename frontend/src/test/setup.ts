import '@testing-library/jest-dom/vitest'
import { server } from './msw'

// Node 24+ ships an experimental global `localStorage` (Web Storage) that has no
// usable backing store unless `--localstorage-file` is set, so it shadows jsdom's
// implementation and makes `localStorage.setItem/clear` throw. Install a small,
// deterministic in-memory Storage so the suite is green on any Node version.
class MemoryStorage {
  private store = new Map<string, string>()
  get length(): number {
    return this.store.size
  }
  clear(): void {
    this.store.clear()
  }
  getItem(key: string): string | null {
    return this.store.has(key) ? this.store.get(key)! : null
  }
  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null
  }
  removeItem(key: string): void {
    this.store.delete(key)
  }
  setItem(key: string, value: string): void {
    this.store.set(key, String(value))
  }
}

const memoryStorage = new MemoryStorage() as unknown as Storage
for (const target of [globalThis, globalThis.window]) {
  Object.defineProperty(target, 'localStorage', {
    configurable: true,
    value: memoryStorage,
  })
}

beforeEach(() => memoryStorage.clear())
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())
