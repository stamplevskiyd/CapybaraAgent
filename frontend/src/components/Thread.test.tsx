/**
 * Tests for the Thread component: message list with markdown, action bar, and autoscroll.
 *
 * Mounts Thread under a real assistant-ui ExternalStoreRuntime seeded with known messages.
 * This is the production rendering path (MarkdownTextPrimitive → MessagePrimitive.Content →
 * MarkdownText → CodeBlock), verifying the Task 5 gap: that fenced code blocks routed through
 * MarkdownTextPrimitive do honour our components.code override.
 */
import { render, screen, renderHook } from '@testing-library/react'
import { AssistantRuntimeProvider } from '@assistant-ui/react'
import { useChatRuntime } from '../chat/runtime'
import { Thread } from './Thread'

// ThreadPrimitive.Viewport uses ResizeObserver for autoscroll detection;
// jsdom does not provide it, so install a no-op stub.
beforeAll(() => {
  if (typeof globalThis.ResizeObserver === 'undefined') {
    globalThis.ResizeObserver = class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  }
})

/** Seed the runtime with user + assistant messages (including a fenced code block). */
function seed() {
  const { result } = renderHook(() =>
    useChatRuntime({
      messages: [
        { id: 'u1', role: 'user', content: 'Вопрос', streaming: false },
        {
          id: 'a1',
          role: 'assistant',
          content: '**Ответ**\n\n```python\nprint(1)\n```',
          streaming: false,
        },
      ],
      isRunning: false,
      onSend: vi.fn().mockResolvedValue(undefined),
      onReload: vi.fn().mockResolvedValue(undefined),
      onCancel: vi.fn(),
    }),
  )
  return result.current
}

test('renders user and assistant messages with markdown', () => {
  const runtime = seed()
  render(
    <AssistantRuntimeProvider runtime={runtime}>
      <Thread />
    </AssistantRuntimeProvider>,
  )
  // User message bubble
  expect(screen.getByText('Вопрос')).toBeInTheDocument()
  // Assistant bold text rendered by MarkdownTextPrimitive
  expect(screen.getByText('Ответ')).toBeInTheDocument()
})

test('fenced code block renders CodeBlock copy button (Task 5 gap)', () => {
  const runtime = seed()
  render(
    <AssistantRuntimeProvider runtime={runtime}>
      <Thread />
    </AssistantRuntimeProvider>,
  )
  // If this assertion FAILS, MarkdownTextPrimitive does NOT honour our components.code override.
  expect(screen.getByRole('button', { name: /копировать/i })).toBeInTheDocument()
})
