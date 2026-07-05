/** Standalone «Память» screen: auto-capture toggle + fact-card grid with add/edit/delete. */
import { useState } from 'react'

/** Russian plural for "факт": 1 → факт, 2–4 → факта, else → фактов (with teens exception). */
function pluralizeFacts(n: number): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return 'факт'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'факта'
  return 'фактов'
}
import { Plus } from 'lucide-react'
import { FactCard } from '../components/FactCard'
import { FactForm } from '../components/FactForm'
import { useFacts } from '../memory/useFacts'
import type { Category } from '../api/types'
import styles from './MemoryScreen.module.css'

export function MemoryScreen() {
  const { facts, autoCapture, addFact, editFact, removeFact, toggleAutoCapture } = useFacts()
  const [editingId, setEditingId] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)

  async function handleAdd(content: string, category: Category) {
    await addFact(content, category)
    setAdding(false)
  }

  async function handleEdit(id: string, content: string, category: Category) {
    await editFact(id, { content, category })
    setEditingId(null)
  }

  return (
    <div className={styles.screen}>
      <div className={styles.inner}>
        <div className={styles.header}>
          <div>
            <h2 className={styles.title}>Память</h2>
            <p className={styles.subtitle}>
              Агент запомнил {facts.length} {pluralizeFacts(facts.length)} о вас и вашей работе.
            </p>
          </div>
          <label className={styles.toggleLabel}>
            Авто-запоминание
            <input
              type="checkbox"
              className={styles.toggle}
              checked={autoCapture}
              onChange={(e) => void toggleAutoCapture(e.target.checked)}
            />
          </label>
        </div>

        <div className={styles.grid}>
          {facts.map((fact) =>
            editingId === fact.id ? (
              <FactForm
                key={fact.id}
                initial={{ content: fact.content, category: fact.category }}
                onSubmit={(content, category) => void handleEdit(fact.id, content, category)}
                onCancel={() => setEditingId(null)}
              />
            ) : (
              <FactCard
                key={fact.id}
                fact={fact}
                onEdit={() => setEditingId(fact.id)}
                onDelete={() => void removeFact(fact.id)}
              />
            ),
          )}
        </div>

        {adding ? (
          <div className={styles.addForm}>
            <FactForm
              submitLabel="Добавить"
              onSubmit={(content, category) => void handleAdd(content, category)}
              onCancel={() => setAdding(false)}
            />
          </div>
        ) : (
          <button type="button" className={styles.addBtn} onClick={() => setAdding(true)}>
            <Plus size={16} />
            Добавить факт вручную
          </button>
        )}
      </div>
    </div>
  )
}
