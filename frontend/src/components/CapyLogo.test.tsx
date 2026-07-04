import { render } from '@testing-library/react'
import { CapyLogo } from './CapyLogo'

test('renders an svg at the requested size', () => {
  const { container } = render(<CapyLogo size={40} />)
  const svg = container.querySelector('svg')
  expect(svg).toBeInTheDocument()
  expect(svg).toHaveAttribute('width', '40')
  expect(svg).toHaveAttribute('viewBox', '0 0 32 32')
})
