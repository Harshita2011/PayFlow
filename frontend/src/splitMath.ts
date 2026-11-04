import { canonicalAmount, minorUnits } from './moneyInput'

export const decimalFromPaise = (value: bigint) => `${value / 100n}.${String(value % 100n).padStart(2, '0')}`

/** Preview only. The server independently validates every amount and participant. */
export function calculateShares(total: string, upiIds: string[], includeCreator: boolean, mode: 'EQUAL' | 'CUSTOM', creatorCustom: string, custom: Record<string, string>) {
  const canonical = canonicalAmount(total.trim())
  const people = [...upiIds].sort()
  if (!people.length || new Set(people).size !== people.length || people.length + Number(includeCreator) > 10) throw new Error('Select unique participants, at most ten people including yourself.')
  const count = BigInt(people.length + Number(includeCreator))
  const totalPaise = minorUnits(canonical)
  let amounts: string[]
  if (mode === 'EQUAL') {
    if (totalPaise < count) throw new Error('The total must provide at least one paise per person.')
    amounts = Array.from({ length: Number(count) }, (_, index) => decimalFromPaise(totalPaise / count + (BigInt(index) < totalPaise % count ? 1n : 0n)))
  } else {
    amounts = [...(includeCreator ? [canonicalAmount(creatorCustom.trim())] : []), ...people.map((upi) => canonicalAmount((custom[upi] || '').trim()))]
    if (amounts.reduce((sum, value) => sum + minorUnits(value), 0n) !== totalPaise) throw new Error('Custom shares must add exactly to the expense total.')
  }
  const creator = includeCreator ? amounts[0] : null
  const others = includeCreator ? amounts.slice(1) : amounts
  return { total: canonical, creator, shares: Object.fromEntries(people.map((upi, index) => [upi, others[index]])) as Record<string, string> }
}
