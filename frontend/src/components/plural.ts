/** Returns the Russian plural form of «факт» for a count. */
export function pluralFacts(n: number): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return 'факт'
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'факта'
  return 'фактов'
}
