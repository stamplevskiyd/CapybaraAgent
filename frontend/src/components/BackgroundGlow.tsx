import styles from './BackgroundGlow.module.css'

/** Fixed wallpaper: base color + two slowly drifting radial glows. */
export function BackgroundGlow() {
  return (
    <div className={styles.root} aria-hidden="true">
      <div className={styles.glowA} data-anim />
      <div className={styles.glowB} data-anim />
    </div>
  )
}
