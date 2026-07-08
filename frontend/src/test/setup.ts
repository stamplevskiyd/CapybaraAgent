import '@testing-library/jest-dom/vitest'
import { transferableAbortController } from 'node:util'
import { server } from './msw'

// The jsdom environment shadows AbortController/AbortSignal with jsdom's own
// implementations, while fetch stays Node's undici. On Node 25+ undici brand-checks
// RequestInit.signal against its internal native class (not instanceof), so every
// fetch carrying a jsdom-realm signal dies with "Expected signal to be an instance
// of AbortSignal" before the request is even made — which broke all streaming tests.
// Restore the true natives (reachable via node:util's transferableAbortController,
// which constructs a real one) as the globals the app code will instantiate.
const nativeController = transferableAbortController()
const NativeAbortController = nativeController.constructor as typeof AbortController
const NativeAbortSignal = nativeController.signal.constructor as typeof AbortSignal
if (globalThis.AbortSignal !== NativeAbortSignal) {
  for (const target of [globalThis, globalThis.window]) {
    Object.defineProperty(target, 'AbortController', {
      configurable: true,
      value: NativeAbortController,
    })
    Object.defineProperty(target, 'AbortSignal', {
      configurable: true,
      value: NativeAbortSignal,
    })
  }
}

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

if (typeof URL.createObjectURL === 'undefined') {
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    value: () => 'blob:capybara-test-url',
  })
}

if (typeof URL.revokeObjectURL === 'undefined') {
  Object.defineProperty(URL, 'revokeObjectURL', {
    configurable: true,
    value: () => {},
  })
}

beforeEach(() => memoryStorage.clear())
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())
