/**
 * Runtime-bound composer: auto-grow input, model selector, tools (visual), send/cancel.
 *
 * Must be rendered inside an `AssistantRuntimeProvider`. Send and cancel are
 * delegated to the assistant-ui runtime (single source of truth for running
 * state). The model pill is a custom child — it does not affect the runtime
 * directly; the parent is responsible for wiring `onSelectModel` into the store.
 *
 * Props removed from the previous implementation: `onSend`, `disabled`,
 * `initialText`. Send now flows through the runtime's `onNew` callback.
 */
import { ComposerPrimitive, ThreadPrimitive } from '@assistant-ui/react'
import { ArrowUp, Paperclip, Square } from 'lucide-react'
import styles from './Composer.module.css'

/**
 * Message composer bound to the assistant-ui runtime.
 *
 * The send button is disabled when no valid model is selected OR the input is
 * empty (assistant-ui auto-disables on empty). Send/Cancel swap based on the
 * runtime's running state via `ThreadPrimitive.If`.
 */
export function Composer({
  models,
  selectedModel,
  onSelectModel,
}: {
  /** Available model names from Ollama. */
  models: string[]
  /** Currently selected model, or null if unset. */
  selectedModel: string | null
  /** Called when the user picks a model from the selector. */
  onSelectModel: (m: string) => void
}) {
  const modelValid = selectedModel !== null && models.includes(selectedModel)
  return (
    <ComposerPrimitive.Root className={styles.composer}>
      <ComposerPrimitive.Input
        className={styles.input}
        rows={1}
        autoFocus
        placeholder="Спросите что-нибудь…"
        submitMode="enter"
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
        {/* Show Send button when thread is idle; disabled also when no valid model. */}
        <ThreadPrimitive.If running={false}>
          <ComposerPrimitive.Send
            className={styles.send}
            aria-label="Отправить"
            disabled={!modelValid}
          >
            <ArrowUp size={18} />
          </ComposerPrimitive.Send>
        </ThreadPrimitive.If>
        {/* Show Cancel button while the LLM is streaming. */}
        <ThreadPrimitive.If running>
          <ComposerPrimitive.Cancel className={styles.send} aria-label="Остановить">
            <Square size={16} />
          </ComposerPrimitive.Cancel>
        </ThreadPrimitive.If>
      </div>
    </ComposerPrimitive.Root>
  )
}
