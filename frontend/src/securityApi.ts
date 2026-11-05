import { apiRequest } from './api'
export interface SecurityStatus { pin_configured: boolean; locked_until: string | null; remaining_attempts: number; single_limit: string; daily_limit: string; daily_count_limit: number; daily_amount_used: string; daily_count_used: number; reset_timezone: 'UTC' }
export interface SecurityEvent { id: string; event_type: string; created_at: string; outcome: string; operation_id: string | null; details: { code?: string; rules?: string[]; risk_level?: string } }
export interface SecurityEvents { items: SecurityEvent[]; next_cursor: string | null }
export interface AuthorizationCommand { operation: 'TRANSFER' | 'SELF_TRANSFER' | 'REQUEST' | 'MOBILE_RECHARGE' | 'BILL_PAYMENT'; payload: object; reference_id?: string }
const headers = (token: string) => ({ Authorization: `Bearer ${token}` })
export const getSecurityStatus = (token: string) => apiRequest<SecurityStatus>('/security/status', { headers: headers(token) })
export const getSecurityEvents = (token: string, before?: string) => apiRequest<SecurityEvents>(`/security/events${before ? `?before=${encodeURIComponent(before)}` : ''}`, { headers: headers(token) })
export const setupPin = (token: string, pin: string, password: string) => apiRequest<{ message: string }>('/security/pin', { method: 'POST', headers: headers(token), body: JSON.stringify({ pin, password }) })
export const changePin = (token: string, current_pin: string, new_pin: string) => apiRequest<{ message: string }>('/security/pin/change', { method: 'POST', headers: headers(token), body: JSON.stringify({ current_pin, new_pin }) })
export const authorizePayment = (token: string, key: string, command: AuthorizationCommand, pin: string) => apiRequest<{ authorization_token: string; expires_at: string; amount?: string; source_account_id?: number }>('/security/payment-authorizations', { method: 'POST', headers: { ...headers(token), 'Idempotency-Key': key }, body: JSON.stringify({ ...command, pin }) })
