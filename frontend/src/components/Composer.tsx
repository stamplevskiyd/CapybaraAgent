/** Message composer: auto-growing textarea, model selector, paperclip (visual), send. */
import { useRef, useState, type KeyboardEvent } from 'react'
import { ArrowUp, Paperclip } from 'lucide-react'
import styles from './Composer.module.css'

/**
 * Textarea + model selector + send button.
 *
 * Send is enabled only when there is non-empty text AND a valid model is selected
 * (`selectedModel` is set and present in `models`). An unselected or stale model
 * (removed from Ollama) highlights the selector and disables send.
 */
export function Composer({
  onSend,
  disabled,
  initialText,
  models,
  selectedModel,
  onSelectModel,
}: {
  onSend: (t: string) => void
  disabled?: boolean
  initialText?: string
  models: string[]
  selectedModel: string | null
  onSelectModel: (m: string) => void
}) {
  const [value, setValue] = useState(initialText ?? '')
  const ref = useRef<HTMLTextAreaElement>(null)

  const modelValid = selectedModel !== null && models.includes(selectedModel)
  const canSend = !disabled && modelValid

  function submit() {
    const text = value.trim()
    if (!text || !canSend) return
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
        <button type="button" className={styles.iconBtn} disabled tabIndex={-1} aria-hidden="true">
          <Paperclip size={18} />
        </button>
        <select
          className={`${styles.modelSelect} ${modelValid ? '' : styles.modelSelectInvalid}`}
          aria-label="Модель"
          value={modelValid ? (selectedModel as string) : ''}
          onChange={(e) => onSelectModel(e.target.value)}
        >
          <option value="" disabled>
            Выберите модель
          </option>
          {models.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
        <div className={styles.spacer} />
        <button
          type="button"
          className={styles.send}
          aria-label="Отправить"
          onClick={submit}
          disabled={!canSend}
        >
          <ArrowUp size={18} />
        </button>
      </div>
    </div>
  )
}
