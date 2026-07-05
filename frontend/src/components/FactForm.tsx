/** Inline form for creating or editing a fact: content textarea + category select. */
import { useState } from 'react'
import type { Category } from '../api/types'
import { CATEGORIES } from '../memory/categories'
import styles from './FactForm.module.css'

export function FactForm({
  initial,
  submitLabel = 'Сохранить',
  onSubmit,
  onCancel,
}: {
  initial?: { content: string; category: Category }
  submitLabel?: string
  onSubmit: (content: string, category: Category) => void
  onCancel: () => void
}) {
  const [content, setContent] = useState(initial?.content ?? '')
  const [category, setCategory] = useState<Category>(initial?.category ?? 'personal')

  const trimmed = content.trim()

  return (
    <div className={styles.form}>
      <textarea
        className={styles.textarea}
        aria-label="Текст факта"
        placeholder="Что запомнить?"
        value={content}
        onChange={(e) => setContent(e.target.value)}
        rows={3}
      />
      <div className={styles.row}>
        <select
          className={styles.select}
          aria-label="Категория"
          value={category}
          onChange={(e) => setCategory(e.target.value as Category)}
        >
          {CATEGORIES.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
        <div className={styles.actions}>
          <button type="button" className={styles.cancel} onClick={onCancel}>
            Отмена
          </button>
          <button
            type="button"
            className={styles.save}
            disabled={!trimmed}
            onClick={() => onSubmit(trimmed, category)}
          >
            {submitLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
