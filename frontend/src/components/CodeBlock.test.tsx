import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CodeBlock } from './CodeBlock'

test('renders code and copies it to the clipboard', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.assign(navigator, { clipboard: { writeText } })
  render(<CodeBlock code="print('hi')" language="python" />)
  const codeBlock = screen.getByRole('code')
  expect(codeBlock.textContent?.includes("print('hi')")).toBeTruthy()
  await userEvent.click(screen.getByRole('button', { name: /копировать/i }))
  expect(writeText).toHaveBeenCalledWith("print('hi')")
})
