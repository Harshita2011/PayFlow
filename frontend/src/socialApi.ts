import { apiRequest } from './api'
import type { PaymentReceipt, TransferInput } from './api'

export interface PublicPerson { display_name: string; upi_id: string }
export interface SavedContact extends PublicPerson { id: string; is_favorite: boolean; created_at: string; updated_at: string }
export interface RecentContact extends PublicPerson { last_interacted_at: string }
export interface MoneyRequest {
  id: string
  requester: PublicPerson
  payer: PublicPerson
  amount: string
  note: string
  status: 'PENDING' | 'PAID' | 'DECLINED' | 'CANCELLED' | 'EXPIRED'
  payment_id: string | null
  created_at: string
  updated_at: string
  expires_at: string
}
export interface RequestPage { items: MoneyRequest[]; next_cursor: string | null; pending_count: number }
const headers = (token: string) => ({ Authorization: `Bearer ${token}` })
export const getContacts = (token: string) => apiRequest<SavedContact[]>('/contacts', { headers: headers(token) })
export const getRecentContacts = (token: string) => apiRequest<RecentContact[]>('/contacts/recent', { headers: headers(token) })
export const addContact = (token: string, upi_id: string) => apiRequest<SavedContact>('/contacts', { method: 'POST', headers: headers(token), body: JSON.stringify({ upi_id }) })
export const removeContact = (token: string, id: string) => apiRequest<void>(`/contacts/${id}`, { method: 'DELETE', headers: headers(token) })
export const favoriteContact = (token: string, id: string, is_favorite: boolean) => apiRequest<SavedContact>(`/contacts/${id}/favorite`, { method: 'PATCH', headers: headers(token), body: JSON.stringify({ is_favorite }) })
export const getRequests = (token: string, direction: 'incoming' | 'outgoing', before?: string) => apiRequest<RequestPage>(`/payment-requests/${direction}${before ? `?before=${encodeURIComponent(before)}` : ''}`, { headers: headers(token) })
export const getMoneyRequest = (token: string, id: string) => apiRequest<MoneyRequest>(`/payment-requests/${id}`, { headers: headers(token) })
export const createMoneyRequest = (token: string, key: string, payload: TransferInput) => apiRequest<MoneyRequest>('/payment-requests', { method: 'POST', headers: { ...headers(token), 'Idempotency-Key': key }, body: JSON.stringify(payload) })
export const closeMoneyRequest = (token: string, id: string, action: 'decline' | 'cancel') => apiRequest<MoneyRequest>(`/payment-requests/${id}/${action}`, { method: 'POST', headers: headers(token), body: '{}' })
export const payMoneyRequest = (token: string, id: string, key: string, sourceId?: number, grant?: string) => apiRequest<PaymentReceipt>(`/payment-requests/${id}/pay`, { method: 'POST', headers: { ...headers(token), 'Idempotency-Key': key, ...(grant ? { 'Payment-Authorization': grant } : {}) }, body: JSON.stringify(sourceId ? { source_account_id: sourceId } : {}) })
