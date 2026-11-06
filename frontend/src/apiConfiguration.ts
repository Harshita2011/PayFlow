// Build-time validation only: VITE_ values are public and must never contain secrets.
export function validateApiBase(value: string, hosted = false): string {
  if (value === '/api' && !hosted) return value
  let url: URL
  try { url = new URL(value) } catch { throw new Error('Configure an HTTPS API origin or the local /api proxy.') }
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
  if (url.username || url.password || url.search || url.hash ||
    !['http:', 'https:'].includes(url.protocol) || (url.protocol === 'http:' && !local) ||
    (hosted && (url.protocol !== 'https:' || local))) {
    throw new Error('API configuration must use HTTPS outside localhost and must not contain credentials, queries or fragments.')
  }
  return value.replace(/\/$/, '')
}
