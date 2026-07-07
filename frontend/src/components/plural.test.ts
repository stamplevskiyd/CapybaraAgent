import { expect, test } from 'vitest'
import { pluralFacts, pluralServers, pluralTools } from './plural'

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

test('pluralTools', () => {
  expect(pluralTools(1)).toBe('инструмент')
  expect(pluralTools(3)).toBe('инструмента')
  expect(pluralTools(5)).toBe('инструментов')
  expect(pluralTools(11)).toBe('инструментов')
})
