/** localStorage helpers for persisting the last-used model selection. */

const KEY = 'capybara.lastModel'

/** Load the last-used model name from localStorage, or null if not set. */
export function loadLastModel(): string | null {
  return localStorage.getItem(KEY)
}

/** Persist the last-used model name to localStorage. */
export function saveLastModel(model: string): void {
  localStorage.setItem(KEY, model)
}
