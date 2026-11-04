/** Indian grouping without ever converting a decimal amount to binary floating point. */
export function formatMoney(value: string): string {
  const [whole, fraction = ''] = value.split('.')
  return `₹${BigInt(whole).toLocaleString('en-IN')}.${fraction.padEnd(2, '0')}`
}
