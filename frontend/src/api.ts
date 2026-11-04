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

export interface BankAccount {
  id: number
  bank_name: string
  masked_account_number: string
  upi_id: string
  balance: string
  created_at: string
  is_primary?: boolean
}

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8001').replace(/\/$/, '')

export class ApiError extends Error {
  status: number
  responseBody: unknown

  constructor(message: string, status: number, responseBody?: unknown) {
    super(message)
    this.status = status
    this.responseBody = responseBody
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
  if (response.ok && response.status === 204) return undefined as T
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = data?.detail
    const message = typeof detail === 'string' ? detail
      : Array.isArray(detail) ? detail.map((error: { loc?: string[]; msg?: string }) =>
        `${error.loc?.at(-1) || 'Input'}: ${error.msg || 'Invalid value'}`).join('. ')
      : 'Something went wrong. Please try again.'
    throw new ApiError(message, response.status, data)
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

export function getAccounts(token: string) {
  return apiRequest<BankAccount[]>('/accounts', { headers: { Authorization: `Bearer ${token}` } })
}

export function getDemoBanks(token: string) {
  return apiRequest<string[]>('/accounts/banks', { headers: { Authorization: `Bearer ${token}` } })
}

export function createAccount(token: string, bank_name: string) {
  return apiRequest<BankAccount>('/accounts', {
    method: 'POST', headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ bank_name }),
  })
}

export interface Recipient {
  display_name: string
  bank_name: string
  upi_id: string
}

export interface TransferInput {
  upi_id: string
  amount: string
  note: string
  source_account_id?: number
}

export interface SelfTransferInput {
  source_account_id: number
  destination_account_id: number
  amount: string
  note: string
}

export interface PaymentReceipt {
  transaction_id: string
  type: 'TRANSFER' | 'DEMO_FUNDING' | 'SELF_TRANSFER'
  direction: 'INCOMING' | 'OUTGOING' | 'FUNDING' | 'SELF'
  status: 'SUCCESS' | 'FAILED'
  amount: string
  currency: 'INR'
  counterparty_name: string
  counterparty_upi_id: string | null
  recipient_upi_id: string | null
  note: string
  failure_reason: string | null
  created_at: string
  source_bank?: string | null
  source_masked_account?: string | null
  destination_bank?: string | null
  destination_masked_account?: string | null
}

export interface PaymentHistory {
  items: PaymentReceipt[]
  next_cursor: string | null
}

export function resolveRecipient(token: string, upi_id: string) {
  return apiRequest<Recipient>('/payments/resolve', {
    method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ upi_id }),
  })
}

export function fundDemo(token: string, key: string, accountId?: number) {
  return apiRequest<PaymentReceipt>('/demo/fund', {
    method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Idempotency-Key': key }, body: JSON.stringify(accountId ? { account_id: accountId } : {}),
  })
}

export function setPrimaryAccount(token: string, id: number) {
  return apiRequest<BankAccount>(`/accounts/${id}/primary`, { method: 'PATCH', headers: { Authorization: `Bearer ${token}` } })
}

export function selfTransfer(token: string, key: string, payload: SelfTransferInput) {
  return apiRequest<PaymentReceipt>('/payments/self-transfer', { method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Idempotency-Key': key }, body: JSON.stringify(payload) })
}

export function transferMoney(token: string, key: string, payload: TransferInput) {
  return apiRequest<PaymentReceipt>('/payments/transfer', {
    method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Idempotency-Key': key }, body: JSON.stringify(payload),
  })
}

export function getPaymentHistory(token: string, before?: string) {
  return apiRequest<PaymentHistory>(`/payments/history${before ? `?before=${encodeURIComponent(before)}` : ''}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
}

export function getPaymentReceipt(token: string, id: string) {
  return apiRequest<PaymentReceipt>(`/payments/${encodeURIComponent(id)}`, { headers: { Authorization: `Bearer ${token}` } })
}
