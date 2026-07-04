/** localStorage helpers for persisting the last-used model selection. */

const KEY = 'capybara.lastModel'

/** Load the last-used model name from localStorage, or null if unset/unavailable. */
export function loadLastModel(): string | null {
  try {
    return localStorage.getItem(KEY)
  } catch {
    return null
  }
}

/** Persist the last-used model name for pre-selecting new chats. */
export function saveLastModel(model: string): void {
  try {
    localStorage.setItem(KEY, model)
  } catch {
    // ignore storage failures — pre-selection is a convenience, not a requirement
  }
}
