const UPI_ID = /^[a-z0-9][a-z0-9-]{0,39}@payflow$/
export const MAX_QR_PAYLOAD_LENGTH = 160

export function createQrPayload(upiId: string): string {
  if (UPI_ID.exec(upiId)?.[0] !== upiId) throw new Error('A valid PayFlow UPI ID is required.')
  return `payflow://pay?v=1&upi=${encodeURIComponent(upiId)}`
}

export function parseQrPayload(content: string, ownUpiId?: string): string {
  if (content.length > MAX_QR_PAYLOAD_LENGTH) throw new Error('This QR payload is too large for PayFlow.')
  // One exact grammar: no URLs to follow, optional fields, aliases, names, or amounts.
  const match = /^payflow:\/\/pay\?v=([0-9]{1,3})&upi=([a-z0-9][a-z0-9-]{0,39})%40payflow$/.exec(content)
  if (!match || match[0] !== content) throw new Error('This is not a valid PayFlow QR code. Use a PayFlow sandbox QR.')
  if (match[1] !== '1') throw new Error('This PayFlow QR version is not supported.')
  const upiId = `${match[2]}@payflow`
  if (upiId === ownUpiId) throw new Error('You cannot pay yourself. Scan another user’s PayFlow QR.')
  return upiId
}
