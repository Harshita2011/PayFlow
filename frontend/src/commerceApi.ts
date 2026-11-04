import { apiRequest } from './api'
import type { PaymentReceipt } from './api'

export interface Operator { id: string; name: string; mobile_pattern?: string; mobile_prefixes?: string }
export interface Plan { id: string; operator_id: string; name: string; price: string; validity_days: number; description: string }
export interface Biller extends Operator { category: string; description: string; reference_format: string }
export interface RechargeInput { mobile: string; plan_id: string; source_account_id: number }
export interface Purchase { kind: 'recharge' | 'bill'; recharge?: RechargeInput; billId?: string; source_account_id: number; amount: string; label: string }
export interface Bill { id: string; biller_id: string; biller: string; category: string; masked_reference: string; billing_period: string; amount_due: string; due_date: string; status: 'UNPAID' | 'PAID' | 'OVERDUE'; created_at: string; paid_at: string | null; receipt: PaymentReceipt | null }
export interface Recharge { id: string; operator: string; plan_id: string; plan_name: string; masked_mobile: string; status: string; created_at: string; receipt: PaymentReceipt }
export interface SavedBiller { id: string; biller_id: string; biller: string; nickname: string; masked_reference: string }
export interface Page<T> { items: T[]; next_cursor: string | null }
const headers = (token: string) => ({ Authorization: `Bearer ${token}` })
export const getOperators = (token: string) => apiRequest<Operator[]>('/recharge/operators', { headers: headers(token) })
export const getPlans = (token: string, operator: string) => apiRequest<Plan[]>(`/recharge/plans?operator_id=${encodeURIComponent(operator)}`, { headers: headers(token) })
export const getBillers = (token: string) => apiRequest<Biller[]>('/billers', { headers: headers(token) })
export const getBill = (token: string, id: string) => apiRequest<Bill>(`/bills/${id}`, { headers: headers(token) })
export const lookupBill = (token: string, biller_id: string, reference: string) => apiRequest<Bill>('/bills/lookup', { method: 'POST', headers: headers(token), body: JSON.stringify({ biller_id, reference }) })
export const getBills = (token: string, before?: string) => apiRequest<Page<Bill>>(`/bills${before ? `?before=${encodeURIComponent(before)}` : ''}`, { headers: headers(token) })
export const getRecharges = (token: string, before?: string) => apiRequest<Page<Recharge>>(`/recharge/history${before ? `?before=${encodeURIComponent(before)}` : ''}`, { headers: headers(token) })
export const getSavedBillers = (token: string) => apiRequest<SavedBiller[]>('/saved-billers', { headers: headers(token) })
export const saveBiller = (token: string, biller_id: string, reference: string, nickname: string) => apiRequest<SavedBiller>('/saved-billers', { method: 'POST', headers: headers(token), body: JSON.stringify({ biller_id, reference, nickname }) })
export const removeBiller = (token: string, id: string) => apiRequest<void>(`/saved-billers/${id}`, { method: 'DELETE', headers: headers(token) })
export const lookupSaved = (token: string, id: string) => apiRequest<Bill>(`/saved-billers/${id}/lookup`, { method: 'POST', headers: headers(token) })
export function payPurchase(token: string, key: string, purchase: Purchase) {
  return apiRequest<PaymentReceipt>(purchase.kind === 'recharge' ? '/recharge' : `/bills/${purchase.billId}/pay`, {
    method: 'POST', headers: { ...headers(token), 'Idempotency-Key': key },
    body: JSON.stringify(purchase.kind === 'recharge' ? purchase.recharge : { source_account_id: purchase.source_account_id }),
  })
}
