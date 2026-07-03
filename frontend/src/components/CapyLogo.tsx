/** Capybara glyph. Fill inherits from --accent; eye is dark. */
export function CapyLogo({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <circle cx="12" cy="9.2" r="2.7" fill="var(--accent,#D89B6C)" />
      <rect x="6.5" y="10.5" width="22" height="12" rx="6" fill="var(--accent,#D89B6C)" />
      <rect x="2.2" y="13.8" width="10.5" height="8" rx="4" fill="var(--accent,#D89B6C)" />
      <rect x="10.8" y="20.5" width="3.8" height="5.4" rx="1.6" fill="var(--accent,#D89B6C)" />
      <rect x="21.4" y="20.5" width="3.8" height="5.4" rx="1.6" fill="var(--accent,#D89B6C)" />
      <circle cx="7.3" cy="15.4" r="1.15" fill="#1c140d" />
    </svg>
  )
}
