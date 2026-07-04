/** Tests for the GFM markdown renderer with sanitize and CodeBlock integration. */
import { render, screen } from '@testing-library/react'
import { TestMarkdownHarness } from './MessageMarkdown'

test('renders a GFM table', () => {
  render(<TestMarkdownHarness text={'| a | b |\n|---|---|\n| 1 | 2 |'} />)
  expect(screen.getByRole('table')).toBeInTheDocument()
  expect(screen.getByText('a')).toBeInTheDocument()
})

test('renders fenced code via CodeBlock', () => {
  render(<TestMarkdownHarness text={'```python\nprint(1)\n```'} />)
  expect(screen.getByRole('button', { name: /копировать/i })).toBeInTheDocument()
})

test('sanitizes raw HTML script out of model output', () => {
  render(<TestMarkdownHarness text={'hello <script>window.__x=1</script> world'} />)
  expect(document.querySelector('script')).toBeNull()
})
