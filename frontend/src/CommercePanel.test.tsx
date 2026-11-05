import { approvePin } from './pinTestHelpers'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import CommercePanel from './CommercePanel'
import PaymentPanel from './PaymentPanel'
import type { Bill } from './commerceApi'

const account = { id: 17, bank_name: 'Orbit Demo Bank', masked_account_number: 'SIM •••• 0017', balance: '1000.00', upi_id: 'learner@payflow', created_at: '', is_primary: true }
const second = { ...account, id: 18, bank_name: 'Grove Demo Bank', balance: '500.00' }
const plan = { id: 'payflow-mobile-99', operator_id: 'payflow-mobile', name: 'Demo Starter', price: '99.00', validity_days: 7, description: 'Fictional data and voice.' }
const provider = { id: 'electric', name: 'PayFlow Electric Demo', category: 'Electricity', description: 'Demo', reference_format: 'DEMO000001' }
const receipt = { transaction_id: 'service-payment-id', type: 'MOBILE_RECHARGE', direction: 'OUTGOING', status: 'SUCCESS', amount: '99.00', currency: 'INR', counterparty_name: 'PayFlow Mobile', counterparty_upi_id: null, recipient_upi_id: null, note: 'Simulated recharge', failure_reason: null, created_at: '2026-11-04T12:00:00Z', source_bank: account.bank_name, source_masked_account: account.masked_account_number }
const bill: Bill = { id: 'bill-id', biller_id: 'electric', biller: provider.name, category: 'Electricity', masked_reference: 'DEMO••0001', billing_period: '2026-11', amount_due: '125.50', due_date: '2026-11-30', status: 'UNPAID', created_at: '', paid_at: null, receipt: null }
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status })
function setup(override?: (path: string, options?: RequestInit) => Promise<Response> | undefined) {
  const mock = vi.fn(async (url: string, options?: RequestInit): Promise<Response> => {
    const path = new URL(url).pathname
    const custom = override?.(path, options)
    if (custom) return custom
    if (path === '/recharge/operators') return json([{ id: 'payflow-mobile', name: 'PayFlow Mobile' }, { id: 'novatel', name: 'NovaTel Demo' }])
    if (path === '/recharge/plans') return json([plan])
    if (path === '/billers') return json([provider])
    if (path === '/bills/lookup') return json(bill)
    if (path === '/bills/bill-id') return json(bill)
    if (path === '/saved-billers') return json([])
    if (path === '/contacts' || path === '/contacts/recent') return json([])
    if (path.startsWith('/payment-requests/')) return json({ items: [], next_cursor: null, pending_count: 0 })
    if (path === '/bills' || path === '/recharge/history' || path === '/payments/history') return json({ items: [], next_cursor: null })
    if (path === '/recharge') return json(receipt, 201)
    return json({ ...receipt, type: 'BILL_PAYMENT', amount: bill.amount_due }, 201)
  })
  vi.stubGlobal('fetch', mock)
  return mock
}
function panel(props = {}) {
  const onPay = vi.fn(), onReceipt = vi.fn(), onLogout = vi.fn()
  const rendered = render(<CommercePanel token="token" accounts={[account, second]} sourceAccountId={17} locked={false} revision={0} onPay={onPay} onReceipt={onReceipt} onLogout={onLogout} {...props} />)
  return { onPay, onReceipt, onLogout, ...rendered }
}
async function rechargeReview() {
  await screen.findByRole('radio', { name: /Demo Starter/ })
  fireEvent.change(screen.getByLabelText('Demo mobile number'), { target: { value: '9876543210' } })
  fireEvent.click(screen.getByRole('radio', { name: /Demo Starter/ }))
  fireEvent.submit(screen.getByRole('form', { name: 'Mobile recharge form' }))
}
async function lookup() {
  await screen.findByRole('radio', { name: /Demo Starter/ })
  fireEvent.click(screen.getByRole('button', { name: 'Utility Bills' }))
  fireEvent.change(screen.getByLabelText('Fictional biller'), { target: { value: 'electric' } })
  fireEvent.change(screen.getByLabelText('Demo customer reference'), { target: { value: 'DEMO000001' } })
  fireEvent.submit(screen.getByRole('form', { name: 'Find demo bill' }))
  await screen.findByRole('article', { name: 'Demo bill details' })
}

describe('Fictional bills and recharge', () => {
  it('loads fictional plans and shows simulation disclosure', async () => {
    setup(); panel()
    await screen.findByRole('radio', { name: /Demo Starter/ })
    expect(screen.getByText(/No mobile service is activated/)).toBeTruthy()
    expect(screen.getByText('7 days · simulated')).toBeTruthy()
  })
  it('requires review and explicit confirmation with a selected source', async () => {
    setup(); const { onPay } = panel()
    await screen.findByRole('radio', { name: /Demo Starter/ })
    fireEvent.change(screen.getByLabelText('Source demo bank account'), { target: { value: '18' } })
    await rechargeReview()
    expect(onPay).not.toHaveBeenCalled()
    expect(screen.getByText(/From Grove Demo Bank/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm simulated payment' }))
    expect(onPay).toHaveBeenCalledWith(expect.objectContaining({ amount: '99.00', recharge: { mobile: '9876543210', plan_id: plan.id, source_account_id: 18 } }))
  })
  it('validates malformed mobile numbers', async () => {
    setup(); const { onPay } = panel()
    await rechargeReview()
    fireEvent.click(screen.getByRole('button', { name: 'Edit service payment' }))
    fireEvent.change(screen.getByLabelText('Demo mobile number'), { target: { value: '123' } })
    fireEvent.click(screen.getByRole('radio', { name: /Demo Starter/ }))
    fireEvent.submit(screen.getByRole('form', { name: 'Mobile recharge form' }))
    expect(screen.getByRole('alert').textContent).toContain('ten-digit')
    expect(onPay).not.toHaveBeenCalled()
  })
  it('blocks unaffordable recharge in red before confirmation', async () => {
    setup(); panel({ accounts: [{ ...account, balance: '20.00' }] })
    await rechargeReview()
    expect(screen.getByRole('alert').className).toContain('error')
    expect(screen.getByRole('alert').textContent).toContain('Insufficient simulated funds')
    expect(screen.queryByRole('button', { name: 'Confirm simulated payment' })).toBeNull()
  })
  it('fetches a stable bill and reviews the server amount', async () => {
    const mock = setup(); const { onPay } = panel()
    await lookup()
    expect(onPay).not.toHaveBeenCalled()
    expect(JSON.parse(String(mock.mock.calls.find(([url]) => url.endsWith('/bills/lookup'))![1]?.body))).toEqual({ biller_id: 'electric', reference: 'DEMO000001' })
    fireEvent.click(screen.getByRole('button', { name: 'Review bill payment' }))
    expect(screen.getByText('₹125.50')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm simulated payment' }))
    expect(onPay).toHaveBeenCalledWith(expect.objectContaining({ kind: 'bill', billId: bill.id, amount: '125.50' }))
  })
  it('shows lookup errors without a payment', async () => {
    setup((path) => path === '/bills/lookup' ? Promise.resolve(json({ detail: 'Demo biller not available' }, 404)) : undefined)
    panel()
    await screen.findByRole('radio', { name: /Demo Starter/ })
    fireEvent.click(screen.getByRole('button', { name: 'Utility Bills' }))
    fireEvent.change(screen.getByLabelText('Fictional biller'), { target: { value: 'electric' } })
    fireEvent.change(screen.getByLabelText('Demo customer reference'), { target: { value: 'DEMO000001' } })
    fireEvent.submit(screen.getByRole('form', { name: 'Find demo bill' }))
    expect((await screen.findByRole('alert')).textContent).toContain('Demo biller not available')
  })
  it('shows loading and empty history states', async () => {
    setup(); panel()
    expect(screen.getByRole('status').textContent).toContain('Loading fictional services')
    await screen.findByRole('radio', { name: /Demo Starter/ })
    fireEvent.click(screen.getByRole('button', { name: 'Service History' }))
    expect(screen.getByText('No simulated recharges yet.')).toBeTruthy()
    expect(screen.getByText('No demo bills yet.')).toBeTruthy()
  })
  it('shows paid bills with linked receipts instead of a pay button', async () => {
    setup((path) => path === '/bills/lookup' ? Promise.resolve(json({ ...bill, status: 'PAID', receipt })) : undefined)
    const { onReceipt } = panel(); await lookup()
    expect(screen.queryByRole('button', { name: 'Review bill payment' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'View bill receipt' }))
    expect(onReceipt).toHaveBeenCalledWith(receipt.transaction_id)
  })
  it('saves a demo biller without leaking its reference in the list', async () => {
    const saved = { id: 'saved-id', biller_id: 'electric', biller: provider.name, nickname: 'Home', masked_reference: 'DEMO••0001' }
    let added = false
    setup((path, options) => { if (path === '/saved-billers') { if (options?.method === 'POST') added = true; return Promise.resolve(json(added ? [saved] : [])) } return undefined })
    panel(); await lookup()
    fireEvent.change(screen.getByLabelText('Biller nickname · optional'), { target: { value: 'Home' } })
    fireEvent.submit(screen.getByRole('form', { name: 'Save demo biller' }))
    await screen.findByText('Demo biller saved.')
    fireEvent.click(screen.getByRole('button', { name: 'Saved Billers' }))
    expect(screen.getByText('Home')).toBeTruthy()
    expect(screen.queryByText('DEMO000001')).toBeNull()
  })
  it('requires confirmation before removing a saved biller', async () => {
    const item = { id: 'saved-id', biller_id: 'electric', biller: provider.name, nickname: 'Home', masked_reference: 'DEMO••0001' }
    const mock = setup((path, options) => path === '/saved-billers' ? Promise.resolve(json([item])) : path === '/saved-billers/saved-id' && options?.method === 'DELETE' ? Promise.resolve(new Response(null, { status: 204 })) : undefined)
    panel(); await screen.findByRole('radio', { name: /Demo Starter/ })
    fireEvent.click(screen.getByRole('button', { name: 'Saved Billers' }))
    fireEvent.click(screen.getByRole('button', { name: 'Remove saved biller' }))
    expect(mock.mock.calls.some(([, options]) => options?.method === 'DELETE')).toBe(false)
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove biller' }))
    await waitFor(() => expect(screen.queryByText('Home')).toBeNull())
  })
  it('handles expired authentication', async () => {
    setup((path) => path === '/billers' ? Promise.resolve(json({ detail: 'Not authenticated' }, 401)) : undefined)
    const { onLogout } = panel()
    await waitFor(() => expect(onLogout).toHaveBeenCalled())
  })
  it('disables actions while a shared payment is unresolved', async () => {
    setup(); panel({ locked: true })
    await screen.findByRole('radio', { name: /Demo Starter/ })
    expect((screen.getByRole('button', { name: 'Utility Bills' }) as HTMLButtonElement).disabled).toBe(true)
  })
  it('uses the existing posting controller and prevents duplicate submit', async () => {
    let resolve!: (response: Response) => void
    const mock = setup((path) => path === '/recharge' ? new Promise<Response>((r) => { resolve = r }) : undefined)
    const changed = vi.fn().mockResolvedValue(undefined)
    render(<PaymentPanel token="token" accountId={17} sourceAccountId={17} accounts={[account]} senderAccount={account} onLogout={vi.fn()} onBalanceChanged={changed} view="bills" />)
    await rechargeReview()
    const button = screen.getByRole('button', { name: 'Confirm simulated payment' })
    fireEvent.click(button); fireEvent.click(button)
    await approvePin()
    await waitFor(() => expect(mock.mock.calls.filter(([url]) => url.endsWith('/recharge')).length).toBe(1))
    expect(JSON.parse(String(mock.mock.calls.find(([url]) => url.endsWith('/recharge'))![1]?.body))).toEqual({ mobile: '9876543210', plan_id: plan.id, source_account_id: 17 })
    resolve(json(receipt, 201))
    await screen.findByRole('article', { name: 'Payment receipt' })
    expect(changed).toHaveBeenCalledOnce()
  })
  it('retains the same key and body after an uncertain network outcome', async () => {
    let calls = 0
    const mock = setup((path) => { if (path === '/recharge') { calls++; return calls === 1 ? Promise.reject(new Error('lost response')) : Promise.resolve(json(receipt, 201)) } return undefined })
    render(<PaymentPanel token="token" accountId={17} sourceAccountId={17} accounts={[account]} senderAccount={account} onLogout={vi.fn()} onBalanceChanged={vi.fn()} view="bills" />)
    await rechargeReview(); fireEvent.click(screen.getByRole('button', { name: 'Confirm simulated payment' }))
    await approvePin()
    fireEvent.click(await screen.findByRole('button', { name: 'Retry same request' }))
    await screen.findByRole('article', { name: 'Payment receipt' })
    const requests = mock.mock.calls.filter(([url]) => url.endsWith('/recharge'))
    expect(requests).toHaveLength(2)
    expect(requests[0][1]?.headers).toEqual(requests[1][1]?.headers)
    expect(requests[0][1]?.body).toEqual(requests[1][1]?.body)
  })
  it('shows insufficient-funds responses without success', async () => {
    setup((path) => path === '/recharge' ? Promise.resolve(json({ detail: 'Insufficient simulated funds' }, 400)) : undefined)
    render(<PaymentPanel token="token" accountId={17} sourceAccountId={17} accounts={[account]} senderAccount={account} onLogout={vi.fn()} onBalanceChanged={vi.fn()} view="bills" />)
    await rechargeReview(); fireEvent.click(screen.getByRole('button', { name: 'Confirm simulated payment' }))
    await approvePin()
    await screen.findByText('Insufficient simulated funds')
    expect(screen.queryByText('Simulated payment completed.')).toBeNull()
  })
  it('pays a bill through the same controller with no client amount', async () => {
    const mock = setup()
    render(<PaymentPanel token="token" accountId={17} sourceAccountId={17} accounts={[account]} senderAccount={account} onLogout={vi.fn()} onBalanceChanged={vi.fn()} view="bills" />)
    await lookup()
    fireEvent.click(screen.getByRole('button', { name: 'Review bill payment' }))
    expect(mock.mock.calls.some(([url]) => url.endsWith('/bills/bill-id/pay'))).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'Confirm simulated payment' }))
    await approvePin()
    await screen.findByRole('article', { name: 'Payment receipt' })
    expect(JSON.parse(String(mock.mock.calls.find(([url]) => url.endsWith('/bills/bill-id/pay'))![1]?.body))).toEqual({ source_account_id: 17 })
  })
  it('recovers a stored purchase after unmount with its original key', async () => {
    const mock = setup()
    const key = 'a21e7082-e874-4a02-ad74-096f8b428631'
    sessionStorage.setItem('payflow.pending.17', JSON.stringify({ key, kind: 'purchase', uncertain: true, purchase: { kind: 'recharge', amount: '99.00', label: 'Demo Starter', source_account_id: 17, recharge: { plan_id: plan.id, source_account_id: 17, mobile: '9876543210' } } }))
    render(<PaymentPanel token="token" accountId={17} accounts={[{ ...account, balance: '0.00' }]} senderAccount={{ ...account, balance: '0.00' }} onLogout={vi.fn()} onBalanceChanged={vi.fn()} view="bills" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Retry same request' }))
    await screen.findByRole('article', { name: 'Payment receipt' })
    const request = mock.mock.calls.find(([url]) => url.endsWith('/recharge'))!
    expect((request[1]?.headers as Record<string, string>)['Idempotency-Key']).toBe(key)
    expect(sessionStorage.getItem('payflow.pending.17')).toBeNull()
  })
  it('repeats a recharge by preselecting the plan but requires a new number and review', async () => {
    const history = { id: 'recharge-id', operator: 'PayFlow Mobile', plan_id: plan.id, plan_name: plan.name, masked_mobile: '••••••3210', status: 'COMPLETED', created_at: receipt.created_at, receipt }
    setup((path) => path === '/recharge/history' ? Promise.resolve(json({ items: [history], next_cursor: null })) : undefined)
    const { onPay } = panel()
    await screen.findByRole('radio', { name: /Demo Starter/ })
    fireEvent.click(screen.getByRole('button', { name: 'Service History' }))
    fireEvent.click(screen.getByRole('button', { name: 'Repeat recharge' }))
    expect((screen.getByLabelText('Demo mobile number') as HTMLInputElement).value).toBe('')
    expect((screen.getByRole('radio', { name: /Demo Starter/ }) as HTMLInputElement).checked).toBe(true)
    expect(onPay).not.toHaveBeenCalled()
  })
  it('uses the backend-configured demo number format', async () => {
    setup((path) => path === '/recharge/operators' ? Promise.resolve(json([{ id: 'payflow-mobile', name: 'PayFlow Mobile', mobile_pattern: '^[5][0-9]{9}$', mobile_prefixes: '5' }])) : undefined)
    const { onPay } = panel()
    await screen.findByRole('radio', { name: /Demo Starter/ })
    fireEvent.change(screen.getByLabelText('Demo mobile number'), { target: { value: '5123456789' } })
    fireEvent.click(screen.getByRole('radio', { name: /Demo Starter/ }))
    fireEvent.submit(screen.getByRole('form', { name: 'Mobile recharge form' }))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm simulated payment' }))
    expect(onPay).toHaveBeenCalledWith(expect.objectContaining({ recharge: expect.objectContaining({ mobile: '5123456789' }) }))
  })
})
