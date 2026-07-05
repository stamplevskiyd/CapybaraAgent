/**
 * Capybara logo image. `size` is the rendered HEIGHT in px; width scales to keep the
 * source aspect ratio (the mark is 684×605, so forcing a square would letterbox it).
 * This matches the design handoff, which sizes the mark by height with `width:auto`.
 * Decorative (`aria-hidden`) — the visible "CapybaraAgent" wordmark provides the name.
 */
import logoUrl from '../assets/capy_mark.png'

export function CapyLogo({ size }: { size: number }) {
  return (
    <img
      src={logoUrl}
      height={size}
      alt=""
      aria-hidden="true"
      style={{ width: 'auto', display: 'block' }}
    />
  )
}
