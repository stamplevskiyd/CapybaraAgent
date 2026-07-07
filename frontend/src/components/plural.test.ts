import { expect, test } from 'vitest'
import { pluralFacts, pluralServers } from './plural'

test('russian plural for facts', () => {
  expect(pluralFacts(1)).toBe('факт')
  expect(pluralFacts(2)).toBe('факта')
  expect(pluralFacts(5)).toBe('фактов')
  expect(pluralFacts(11)).toBe('фактов')
  expect(pluralFacts(21)).toBe('факт')
  expect(pluralFacts(12)).toBe('фактов')
  expect(pluralFacts(13)).toBe('фактов')
  expect(pluralFacts(14)).toBe('фактов')
})

test('pluralServers', () => {
  expect(pluralServers(1)).toBe('сервер')
  expect(pluralServers(3)).toBe('сервера')
  expect(pluralServers(5)).toBe('серверов')
  expect(pluralServers(11)).toBe('серверов')
})
