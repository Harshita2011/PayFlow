export function canonicalAmount(value: string): string {
  if (!/^[0-9]{1,16}(\.[0-9]{1,2})?$/.test(value)) throw new Error('Enter an amount with at most two decimal places.')
  const [whole, fraction = ''] = value.split('.')
  const cents = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'))
  if (cents <= 0n || cents > 10000000n) throw new Error('Send between ₹0.01 and ₹100,000.00 in simulated funds.')
  return `${BigInt(whole)}.${fraction.padEnd(2, '0')}`
}

export function minorUnits(value: string): bigint {
  const [whole, fraction = ''] = value.split('.')
  return BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'))
}
