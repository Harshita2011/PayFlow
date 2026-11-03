export interface User {
  id: number
  full_name: string
  email: string
  created_at: string
}

export interface LoginResult {
  access_token: string
  token_type: 'bearer'
  expires_in: number
}

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8001').replace(/\/$/, '')

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

export async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      cache: 'no-store',
      signal: AbortSignal.timeout(10000),
      headers: { 'Content-Type': 'application/json', ...options.headers },
    })
  } catch {
    throw new ApiError('Could not reach PayFlow. Check that the backend is running and try again.', 0)
  }
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = data?.detail
    const message = typeof detail === 'string' ? detail
      : Array.isArray(detail) ? detail.map((error: { loc?: string[]; msg?: string }) =>
        `${error.loc?.at(-1) || 'Input'}: ${error.msg || 'Invalid value'}`).join('. ')
      : 'Something went wrong. Please try again.'
    throw new ApiError(message, response.status)
  }
  if (data === null) throw new ApiError('The server returned an unexpected response. Please try again.', response.status)
  return data as T
}

export function registerUser(full_name: string, email: string, password: string) {
  return apiRequest<User>('/register', {
    method: 'POST', body: JSON.stringify({ full_name, email, password }),
  })
}

export function loginUser(email: string, password: string) {
  return apiRequest<LoginResult>('/login', {
    method: 'POST', body: JSON.stringify({ email, password }),
  })
}

export function getProfile(token: string) {
  return apiRequest<User>('/me', { headers: { Authorization: `Bearer ${token}` } })
}
