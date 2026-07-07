/** Modal wizard to attach an HTTP MCP server: form → checking → success | error. */
import { useState } from 'react'
import { Plug, Plus, X } from 'lucide-react'
import { ApiError } from '../api/client'
import type { McpServerOut } from '../api/types'
import styles from './ConnectWizard.module.css'

type Step = 'form' | 'checking' | 'success' | 'error'
interface HeaderRow {
  key: string
  value: string
}

/** Extract a human message from a failed connect attempt. */
function errorDetail(err: unknown): string {
  if (err instanceof ApiError) {
    try {
      const body = JSON.parse(err.message) as { detail?: string }
      if (body.detail) return body.detail
    } catch {
      // non-JSON body — fall through to status-based copy
    }
    if (err.status === 502) return 'Сервер недоступен'
  }
  return 'Не удалось подключиться'
}

function rowsToRecord(rows: HeaderRow[]): Record<string, string> {
  const out: Record<string, string> = {}
  for (const r of rows) {
    const k = r.key.trim()
    if (k) out[k] = r.value
  }
  return out
}

export function ConnectWizard({
  onConnect,
  onClose,
}: {
  onConnect: (name: string, url: string, headers: Record<string, string>) => Promise<McpServerOut>
  onClose: () => void
}) {
  const [step, setStep] = useState<Step>('form')
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [rows, setRows] = useState<HeaderRow[]>([])
  const [result, setResult] = useState<McpServerOut | null>(null)
  const [error, setError] = useState('')

  const canSubmit = name.trim() !== '' && url.trim() !== ''

  async function submit() {
    setStep('checking')
    try {
      const server = await onConnect(name.trim(), url.trim(), rowsToRecord(rows))
      setResult(server)
      setStep('success')
    } catch (err) {
      setError(errorDetail(err))
      setStep('error')
    }
  }

  function setRow(i: number, patch: Partial<HeaderRow>) {
    setRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))
  }

  return (
    <div
      className={styles.overlay}
      onClick={() => {
        if (step !== 'checking') onClose()
      }}
    >
      <div className={styles.card} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <span className={styles.headerIcon}>
            <Plug size={16} />
          </span>
          <div className={styles.headerText}>
            <span className={styles.title}>Подключение MCP-сервера</span>
            <span className={styles.subtitle}>Локально · ключи не покидают устройство</span>
          </div>
          <button type="button" className={styles.close} aria-label="Закрыть" onClick={() => {
            if (step !== 'checking') onClose()
          }}>
            <X size={16} />
          </button>
        </div>

        {step === 'form' && (
          <div className={styles.body}>
            <label className={styles.field}>
              Название
              <input
                className={styles.input}
                aria-label="Название"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="github"
              />
            </label>
            <label className={styles.field}>
              URL
              <input
                className={`${styles.input} ${styles.mono}`}
                aria-label="URL"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://mcp.example/github"
              />
            </label>

            <div className={styles.headersBlock}>
              <span className={styles.caption}>Заголовки (опционально)</span>
              {rows.map((r, i) => (
                <div className={styles.headerRow} key={i}>
                  <input
                    className={`${styles.input} ${styles.mono}`}
                    aria-label={`Ключ заголовка ${i + 1}`}
                    value={r.key}
                    onChange={(e) => setRow(i, { key: e.target.value })}
                    placeholder="Authorization"
                  />
                  <input
                    className={`${styles.input} ${styles.mono}`}
                    aria-label={`Значение заголовка ${i + 1}`}
                    value={r.value}
                    onChange={(e) => setRow(i, { value: e.target.value })}
                    placeholder="Bearer …"
                  />
                  <button
                    type="button"
                    className={styles.iconBtn}
                    aria-label={`Удалить заголовок ${i + 1}`}
                    onClick={() => setRows((prev) => prev.filter((_, idx) => idx !== i))}
                  >
                    <X size={14} />
                  </button>
                </div>
              ))}
              <button
                type="button"
                className={styles.addHeader}
                onClick={() => setRows((prev) => [...prev, { key: '', value: '' }])}
              >
                <Plus size={13} /> Добавить заголовок
              </button>
            </div>

            <div className={styles.info}>
              Агент может подключить сервер и сам — попросите его в чате.
            </div>

            <div className={styles.footer}>
              <button type="button" className={styles.cancel} onClick={onClose}>
                Отмена
              </button>
              <button
                type="button"
                className={styles.primary}
                disabled={!canSubmit}
                onClick={submit}
              >
                Подключить
              </button>
            </div>
          </div>
        )}

        {step === 'checking' && (
          <div className={styles.centered}>
            <div className={styles.spinner} />
            <span className={styles.title}>Проверяем соединение…</span>
          </div>
        )}

        {step === 'success' && result && (
          <div className={styles.body}>
            <div className={styles.centered}>
              <div className={styles.successIcon}>✓</div>
              <span className={styles.title}>Сервер подключён</span>
              <span className={styles.subtitle}>Обнаружено {result.tools.length}</span>
            </div>
            <div className={styles.chips}>
              {result.tools.map((t) => (
                <span className={styles.chip} key={t.id}>
                  {t.name}
                </span>
              ))}
            </div>
            <div className={styles.footer}>
              <button type="button" className={styles.primary} onClick={onClose}>
                Готово
              </button>
            </div>
          </div>
        )}

        {step === 'error' && (
          <div className={styles.body}>
            <div className={styles.centered}>
              <div className={styles.errorIcon}>!</div>
              <span className={styles.title}>Не удалось подключиться</span>
              <span className={styles.errorText}>{error}</span>
            </div>
            <div className={styles.footer}>
              <button type="button" className={styles.cancel} onClick={() => setStep('form')}>
                Назад
              </button>
              <button type="button" className={styles.primary} onClick={submit}>
                Повторить
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
