import { render } from '@testing-library/react'
import { CapyLogo } from './CapyLogo'

test('renders the logo image at the requested size', () => {
  const { container } = render(<CapyLogo size={40} />)
  const img = container.querySelector('img')
  expect(img).toBeInTheDocument()
  expect(img).toHaveAttribute('width', '40')
  expect(img).toHaveAttribute('height', '40')
})
