/** Message composer: auto-growing textarea, paperclip (visual), and send button. */
import { useRef, useState, type KeyboardEvent } from 'react'
import { ArrowUp, Paperclip } from 'lucide-react'
import styles from './Composer.module.css'

/** Textarea + send button; submits on Enter (not Shift+Enter) or button click, then clears. */
export function Composer({ onSend, disabled }: { onSend: (t: string) => void; disabled?: boolean }) {
  const [value, setValue] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)

  function submit() {
    const text = value.trim()
    if (!text || disabled) return
    onSend(text)
    setValue('')
    if (ref.current) ref.current.style.height = 'auto'
  }
  function onKeyDown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }
  return (
    <div className={styles.composer}>
      <textarea
        ref={ref}
        className={styles.input}
        value={value}
        rows={1}
        placeholder="Спросите что-нибудь…"
        onChange={(e) => {
          setValue(e.target.value)
          e.target.style.height = 'auto'
          e.target.style.height = `${e.target.scrollHeight}px`
        }}
        onKeyDown={onKeyDown}
      />
      <div className={styles.row}>
        <button type="button" className={styles.iconBtn} aria-label="Прикрепить">
          <Paperclip size={18} />
        </button>
        <div className={styles.spacer} />
        <button type="button" className={styles.send} aria-label="Отправить" onClick={submit}>
          <ArrowUp size={18} />
        </button>
      </div>
    </div>
  )
}
