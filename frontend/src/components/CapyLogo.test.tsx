import { render } from '@testing-library/react'
import { CapyLogo } from './CapyLogo'

test('renders the logo at the requested height with aspect-preserving width', () => {
  const { container } = render(<CapyLogo size={40} />)
  const img = container.querySelector('img')
  expect(img).toBeInTheDocument()
  // `size` sets the height; width is auto so the non-square mark is not letterboxed.
  expect(img).toHaveAttribute('height', '40')
  expect(img).not.toHaveAttribute('width')
  expect(img).toHaveStyle({ width: 'auto' })
})
