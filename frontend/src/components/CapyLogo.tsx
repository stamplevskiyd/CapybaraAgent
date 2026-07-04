/** Capybara logo image, rendered at the requested square size on a transparent background. */
import logoUrl from '../assets/capy_mark.png'

export function CapyLogo({ size }: { size: number }) {
  return (
    <img
      src={logoUrl}
      width={size}
      height={size}
      alt=""
      aria-hidden="true"
      style={{ objectFit: 'contain', display: 'block' }}
    />
  )
}
