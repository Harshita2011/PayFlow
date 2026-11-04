import { apiRequest } from './api'
import type { PublicPerson } from './socialApi'

export interface SplitCreateInput {
  title: string
  description: string
  total_amount: string
  include_creator: boolean
  mode: 'EQUAL' | 'CUSTOM'
  creator_share?: string
  participants: { upi_id: string; share_amount?: string }[]
}
export interface SplitParticipant {
  id: string
  person: PublicPerson
  share_amount: string
  is_creator_share: boolean
  status: 'CREATOR_SHARE' | 'PENDING' | 'PAID' | 'DECLINED' | 'CANCELLED' | 'EXPIRED'
  request_id: string | null
  payment_id: string | null
  can_pay: boolean
  attempts: { request_id: string; status: string; payment_id: string | null; created_at: string }[]
}
export interface ExpenseSplit {
  id: string
  title: string
  description: string
  total_amount: string
  creator_share: string
  contributions_received: string
  outstanding_amount: string
  currency: 'INR'
  expense_model: 'EXTERNAL_RECORD'
  status: 'OPEN' | 'SETTLED' | 'CANCELLED'
  creator: PublicPerson
  is_creator: boolean
  participant_count: number
  participants: SplitParticipant[]
  created_at: string
  updated_at: string
}
export interface SplitPage { items: ExpenseSplit[]; next_cursor: string | null }
export type SplitScope = 'all' | 'created' | 'shared' | 'settled'
const auth = (token: string) => ({ Authorization: `Bearer ${token}` })
export const getSplits = (token: string, scope: SplitScope, before?: string) => apiRequest<SplitPage>(`/splits?scope=${scope}${before ? `&before=${encodeURIComponent(before)}` : ''}`, { headers: auth(token) })
export const getSplit = (token: string, id: string) => apiRequest<ExpenseSplit>(`/splits/${id}`, { headers: auth(token) })
export const createSplit = (token: string, key: string, payload: SplitCreateInput) => apiRequest<ExpenseSplit>('/splits', { method: 'POST', headers: { ...auth(token), 'Idempotency-Key': key }, body: JSON.stringify(payload) })
export const cancelSplit = (token: string, id: string) => apiRequest<ExpenseSplit>(`/splits/${id}/cancel`, { method: 'POST', headers: auth(token), body: '{}' })
export const renewShare = (token: string, id: string, participant: string, key: string) => apiRequest<ExpenseSplit>(`/splits/${id}/participants/${participant}/renew`, { method: 'POST', headers: { ...auth(token), 'Idempotency-Key': key }, body: '{}' })
