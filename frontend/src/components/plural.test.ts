import { expect, test } from 'vitest'
import { pluralFacts } from './plural'

test('russian plural for facts', () => {
  expect(pluralFacts(1)).toBe('факт')
  expect(pluralFacts(2)).toBe('факта')
  expect(pluralFacts(5)).toBe('фактов')
  expect(pluralFacts(11)).toBe('фактов')
  expect(pluralFacts(21)).toBe('факт')
})
