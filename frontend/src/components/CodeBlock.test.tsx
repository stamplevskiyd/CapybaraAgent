/** Tests for the syntax-highlighted code block. */
import { render } from '@testing-library/react'
import { CodeBlock } from './CodeBlock'

test('highlights a registered language into Prism tokens', () => {
  const { container } = render(<CodeBlock code={'def f():\n    return 1'} language="python" />)
  const tokens = Array.from(container.querySelectorAll<HTMLElement>('span.token'))
  const def = tokens.find((t) => t.textContent === 'def')
  expect(def).toBeDefined()
  // The keyword colour from prismTheme (#c58fd6) is applied inline by PrismLight.
  expect(def!.style.color).toBe('rgb(197, 143, 214)')
})

test('highlights common fence aliases like "py"', () => {
  const { container } = render(<CodeBlock code={'def f():\n    return 1'} language="py" />)
  expect(container.querySelector('span.token')).not.toBeNull()
})

test('falls back to plain text for an unknown language', () => {
  const { container } = render(<CodeBlock code={'foo bar'} language="klingon" />)
  expect(container.querySelector('span.token')).toBeNull()
  expect(container.textContent).toContain('foo bar')
})
