/** Fixed fact categories with their RU labels and design-handoff colours. */
import type { Category } from '../api/types'

export interface CategoryMeta {
  value: Category
  label: string
  color: string
  bg: string
}

export const CATEGORIES: CategoryMeta[] = [
  { value: 'personal', label: 'Личное', color: '#D89B6C', bg: 'rgba(216,155,108,0.14)' },
  { value: 'project', label: 'Проект', color: '#7fa8d0', bg: 'rgba(127,168,208,0.14)' },
  { value: 'preference', label: 'Предпочтения', color: '#8fbf9e', bg: 'rgba(143,191,158,0.14)' },
]

export const CATEGORY_BY_VALUE: Record<Category, CategoryMeta> = Object.fromEntries(
  CATEGORIES.map((c) => [c.value, c]),
) as Record<Category, CategoryMeta>
