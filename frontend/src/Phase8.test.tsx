import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import AccountPanel from './AccountPanel'
import PaymentPanel from './PaymentPanel'
import SelfTransferPanel from './SelfTransferPanel'
import SplitPanel from './SplitPanel'
import PaymentHistory from './PaymentHistory'
import { calculateShares } from './splitMath'
import type { BankAccount, PaymentReceipt } from './api'
import type { ExpenseSplit } from './splitApi'

const a: BankAccount = { id: 1, bank_name: 'Grove Demo Bank', masked_account_number: 'SIM •••• 1111', upi_id: 'asha@payflow', balance: '1000.00', is_primary: true, created_at: '2026-11-04T00:00:00Z' }
const b: BankAccount = { ...a, id: 4, bank_name: 'Orbit Demo Bank', masked_account_number: 'SIM •••• 4444', upi_id: 'asha-second@payflow', balance: '0.00', is_primary: false }
const ravi = { display_name: 'Ravi Learner', upi_id: 'ravi@payflow' }
const eva = { display_name: 'Eva Learner', upi_id: 'eva@payflow' }
const contacts = [ravi, eva].map((person, index) => ({ ...person, id: `contact-${index}`, is_favorite: false, created_at: a.created_at, updated_at: a.created_at }))
const requestId = '7648f357-ea74-4c9a-b9f6-c6024d9f3d52'
const split: ExpenseSplit = { id: 'split-one', title: 'Dinner', description: 'External restaurant bill', total_amount: '100.00', creator_share: '50.00', contributions_received: '0.00', outstanding_amount: '50.00', currency: 'INR', expense_model: 'EXTERNAL_RECORD', status: 'OPEN', creator: { display_name: 'Asha', upi_id: a.upi_id }, is_creator: true, participant_count: 2, created_at: a.created_at, updated_at: a.created_at, participants: [
  { id: 'creator-share', person: { display_name: 'Asha', upi_id: a.upi_id }, share_amount: '50.00', is_creator_share: true, status: 'CREATOR_SHARE', request_id: null, payment_id: null, can_pay: false, attempts: [] },
  { id: 'ravi-share', person: ravi, share_amount: '50.00', is_creator_share: false, status: 'PENDING', request_id: requestId, payment_id: null, can_pay: false, attempts: [{ request_id: requestId, status: 'PENDING', payment_id: null, created_at: a.created_at }] },
] }
const receipt: PaymentReceipt = { transaction_id: 'self-receipt', type: 'SELF_TRANSFER', direction: 'SELF', status: 'SUCCESS', amount: '700.00', currency: 'INR', counterparty_name: 'Transfer between your accounts', counterparty_upi_id: b.upi_id, recipient_upi_id: b.upi_id, note: '', failure_reason: null, created_at: a.created_at, source_bank: a.bank_name, source_masked_account: a.masked_account_number, destination_bank: b.bank_name, destination_masked_account: b.masked_account_number }
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
function setup(override?: (url: string, init?: RequestInit) => Promise<Response> | undefined) {
  const mock = vi.fn(async (url: string, init?: RequestInit) => {
    const result = override?.(url, init)
    if (result) return result
    if (url.includes('/splits?')) return json({ items: [split], next_cursor: null })
    if (url.includes('/splits')) return json(split, init?.method === 'POST' ? 201 : 200)
    if (url.endsWith('/contacts')) return json(contacts)
    if (url.includes('/contacts/recent')) return json([])
    if (url.includes('/payment-requests/incoming') || url.includes('/payment-requests/outgoing')) return json({ items: [], next_cursor: null, pending_count: 0 })
    if (url.includes('/payment-requests/')) return json({ id: requestId, requester: split.creator, payer: ravi, amount: '50.00', note: 'Split: Dinner', status: 'PENDING', payment_id: null, created_at: a.created_at, updated_at: a.created_at, expires_at: '2030-11-11T00:00:00Z' })
    if (url.includes('/payments/history')) return json({ items: [], next_cursor: null })
    if (url.endsWith('/payments/resolve')) return json({ ...ravi, bank_name: 'River Demo Bank' })
    if (url.endsWith('/accounts/banks')) return json(['Grove Demo Bank', 'Orbit Demo Bank'])
    if (url.endsWith('/accounts')) return json([a,b])
    return json(receipt, 201)
  })
  vi.stubGlobal('fetch', mock)
  return mock
}
function splitPanel(view: 'split-create' | 'splits' = 'split-create') {
  const props = { token: 'secret-token', accountId: 1, view, revision: 0, locked: false, senderAccount: a, onNavigate: vi.fn(), onLogout: vi.fn(), onPay: vi.fn().mockResolvedValue(undefined), onReceipt: vi.fn().mockResolvedValue(undefined) }
  return { ...render(<SplitPanel {...props} />), props }
}
async function splitForm() {
  await screen.findByRole('option', { name: 'Ravi Learner · ravi@payflow' })
  fireEvent.change(screen.getByLabelText('Add saved contact'), { target: { value: ravi.upi_id } })
  fireEvent.change(screen.getByLabelText('Add saved contact'), { target: { value: eva.upi_id } })
  fireEvent.change(screen.getByLabelText('Expense title'), { target: { value: 'Dinner' } })
  fireEvent.change(screen.getByLabelText('Total expense · INR'), { target: { value: '100.00' } })
  fireEvent.click(screen.getByLabelText('This is an externally paid expense record, not a verified PayFlow bill payment.'))
}
function selfForm() {
  fireEvent.change(screen.getByLabelText('To bank account'), { target: { value: b.id } })
  fireEvent.change(screen.getByLabelText('Self transfer amount · INR'), { target: { value: '700.00' } })
  fireEvent.submit(screen.getByRole('form', { name: 'Enter self transfer' }))
}

describe('Phase 8 split and account experience', () => {
  it('previews exact equal paise rounding in deterministic creator-first order', () => {
    const shares = calculateShares('100', [ravi.upi_id, eva.upi_id], true, 'EQUAL', '', {})
    expect(shares.creator).toBe('33.34')
    expect(shares.shares).toEqual({ [eva.upi_id]: '33.33', [ravi.upi_id]: '33.33' })
    expect(() => calculateShares('0.01', [ravi.upi_id], true, 'EQUAL', '', {})).toThrow(/one paise/)
  })

  it('validates exact custom sums and rejects duplicates', () => {
    expect(calculateShares('100.00', [ravi.upi_id], true, 'CUSTOM', '40', { [ravi.upi_id]: '60.00' }).creator).toBe('40.00')
    expect(() => calculateShares('100', [ravi.upi_id], true, 'CUSTOM', '40', { [ravi.upi_id]: '60.01' })).toThrow(/add exactly/)
    expect(() => calculateShares('100', [ravi.upi_id, ravi.upi_id], false, 'EQUAL', '', {})).toThrow(/unique/)
  })

  it('reviews creator and participant shares before creating an expense, without moving money', async () => {
    const mock = setup()
    const { props } = splitPanel()
    await splitForm()
    expect(screen.getByText('₹33.34')).toBeTruthy()
    fireEvent.submit(screen.getByRole('form', { name: 'Create expense split' }))
    expect(mock.mock.calls.some(([url, init]) => url.endsWith('/splits') && init?.method === 'POST')).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'Confirm and create split' }))
    await screen.findByText('Split created. No money moved.')
    const posted = mock.mock.calls.find(([url, init]) => url.endsWith('/splits') && init?.method === 'POST')!
    const body = JSON.parse(String(posted[1]?.body))
    expect(body.total_amount).toBe('100.00')
    expect(body.participants).toEqual([{ upi_id: eva.upi_id }, { upi_id: ravi.upi_id }])
    expect(props.onNavigate).toHaveBeenCalledWith('splits')
    expect(mock.mock.calls.some(([url]) => url.endsWith('/pay') || url.endsWith('/transfer'))).toBe(false)
  })

  it('allows custom split input and blocks mismatched totals before review', async () => {
    setup(); splitPanel(); await splitForm()
    fireEvent.change(screen.getByLabelText('Split method'), { target: { value: 'CUSTOM' } })
    fireEvent.change(screen.getByLabelText('My custom share'), { target: { value: '20.00' } })
    fireEvent.change(screen.getByLabelText('Share for Eva Learner'), { target: { value: '40.00' } })
    fireEvent.change(screen.getByLabelText('Share for Ravi Learner'), { target: { value: '50.00' } })
    fireEvent.submit(screen.getByRole('form', { name: 'Create expense split' }))
    expect(screen.getByRole('alert').textContent).toContain('add exactly')
    fireEvent.change(screen.getByLabelText('Share for Ravi Learner'), { target: { value: '40.00' } })
    fireEvent.submit(screen.getByRole('form', { name: 'Create expense split' }))
    expect(screen.getByRole('button', { name: 'Confirm and create split' })).toBeTruthy()
  })

  it('prevents duplicate participants and handles lookup errors', async () => {
    setup((url) => url.endsWith('/payments/resolve') ? Promise.resolve(json({ detail: 'Recipient not available' }, 404)) : undefined)
    splitPanel(); await splitForm()
    fireEvent.change(screen.getByLabelText('Add saved contact'), { target: { value: ravi.upi_id } })
    expect(screen.getByRole('alert').textContent).toContain('already included')
    fireEvent.change(screen.getByLabelText('Participant UPI ID'), { target: { value: 'unknown@payflow' } })
    fireEvent.submit(screen.getByRole('form', { name: 'Verify split participant' }))
    await screen.findByText('Recipient not available')
  })

  it('restores an unknown split creation and reuses its exact key/payload', async () => {
    let posts = 0
    const mock = setup((url, init) => url.endsWith('/splits') && init?.method === 'POST' && ++posts === 1 ? Promise.reject(new TypeError('Response lost')) : undefined)
    const view = splitPanel(); await splitForm()
    fireEvent.submit(screen.getByRole('form', { name: 'Create expense split' }))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm and create split' }))
    await screen.findByText(/Outcome unknown/)
    expect(sessionStorage.getItem('payflow.split-operation.1')).not.toContain('secret-token')
    view.unmount(); splitPanel()
    fireEvent.click(screen.getByRole('button', { name: 'Retry same split action' }))
    await screen.findByText('Split created. No money moved.')
    const requests = mock.mock.calls.filter(([url, init]) => url.endsWith('/splits') && init?.method === 'POST')
    expect(requests[0][1]?.headers).toEqual(requests[1][1]?.headers)
    expect(requests[0][1]?.body).toBe(requests[1][1]?.body)
  })

  it('shows server-derived progress and opens the same linked Phase 7 request', async () => {
    setup(); splitPanel('splits')
    fireEvent.click(await screen.findByRole('button', { name: /Dinner.*2 people/ }))
    const details = await screen.findByRole('region', { name: 'Split details' })
    expect(details.textContent).toContain('CREATOR SHARE · EXTERNAL')
    expect(details.textContent).toContain('Contributions received')
    fireEvent.click(within(details).getByRole('button', { name: 'Open linked request' }))
    expect((await screen.findByRole('region', { name: 'Linked money request' })).textContent).toContain('same obligation shown in Requests')
  })

  it('requires explicit contribution confirmation with the original request ID', async () => {
    const shared = { ...split, is_creator: false, participants: [split.participants[0], { ...split.participants[1], can_pay: true }] }
    setup((url) => url.includes('/splits') ? Promise.resolve(json(url.includes('?') ? { items: [shared], next_cursor: null } : shared)) : undefined)
    const { props } = splitPanel('splits')
    fireEvent.click(await screen.findByRole('button', { name: /Dinner.*2 people/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Pay my share' }))
    const dialog = await screen.findByRole('dialog', { name: 'Confirm split contribution' })
    expect(props.onPay).not.toHaveBeenCalled()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm and pay share' }))
    await waitFor(() => expect(props.onPay).toHaveBeenCalledWith(expect.objectContaining({ id: requestId, amount: '50.00' })))
  })

  it('requires cancellation confirmation and never offers it after a contribution is paid', async () => {
    const mock = setup()
    splitPanel('splits')
    fireEvent.click(await screen.findByRole('button', { name: /Dinner.*2 people/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel unpaid split' }))
    expect(mock.mock.calls.some(([url]) => url.endsWith('/cancel'))).toBe(false)
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm split cancellation' }))
    await screen.findByText('Split cancelled. No payments were erased or refunded.')
  })

  it('shows empty splits, filters, loading and safe server errors', async () => {
    setup((url) => url.includes('/splits?') ? Promise.resolve(json({ items: [], next_cursor: null })) : undefined)
    splitPanel('splits')
    expect(screen.getByText('Loading splits and saved contacts…')).toBeTruthy()
    await screen.findByText(/No splits here yet/)
    fireEvent.change(screen.getByLabelText('Show splits'), { target: { value: 'settled' } })
    expect((screen.getByLabelText('Show splits') as HTMLSelectElement).value).toBe('settled')
  })

  it('reviews self transfer account masks and waits for explicit confirmation', async () => {
    const pay = vi.fn().mockResolvedValue(undefined)
    render(<SelfTransferPanel accounts={[a,b]} locked={false} onPay={pay} />)
    selfForm()
    expect(pay).not.toHaveBeenCalled()
    expect(screen.getByText(/From Grove Demo Bank/).textContent).toContain('1111')
    fireEvent.click(screen.getByRole('button', { name: 'Confirm self transfer' }))
    expect(pay).toHaveBeenCalledWith({ source_account_id: 1, destination_account_id: 4, amount: '700.00', note: '' })
  })

  it('blocks same-account, zero, overprecision and insufficient self transfers', () => {
    render(<SelfTransferPanel accounts={[a,b]} locked={false} onPay={vi.fn()} />)
    for (const [target, amount] of [[a.id,'1.00'], [b.id,'0'], [b.id,'1.001'], [b.id,'1000.01']]) {
      fireEvent.change(screen.getByLabelText('To bank account'), { target: { value: target } })
      fireEvent.change(screen.getByLabelText('Self transfer amount · INR'), { target: { value: amount } })
      fireEvent.submit(screen.getByRole('form', { name: 'Enter self transfer' }))
      expect(screen.getByRole('alert')).toBeTruthy()
      expect(screen.queryByRole('button', { name: 'Confirm self transfer' })).toBeNull()
    }
  })

  it('self transfer integrates with the existing retry/receipt and balance refresh path', async () => {
    let sends = 0
    const mock = setup((url) => url.endsWith('/payments/self-transfer') && ++sends === 1 ? Promise.reject(new TypeError('Lost response')) : undefined)
    const balance = vi.fn().mockResolvedValue(undefined)
    const props = { token: 'token', accountId: 1, sourceAccountId: 1, senderAccount: a, accounts: [a,b], view: 'self' as const, onLogout: vi.fn(), onBalanceChanged: balance }
    const view = render(<PaymentPanel {...props} />)
    selfForm(); fireEvent.click(screen.getByRole('button', { name: 'Confirm self transfer' }))
    await screen.findByText('Keep this payment request.')
    view.unmount()
    render(<PaymentPanel {...props} senderAccount={{ ...a, balance: '300.00' }} accounts={[{ ...a, balance: '300.00' }, { ...b, balance: '700.00' }]} />)
    fireEvent.click(screen.getByRole('button', { name: 'Retry same request' }))
    await screen.findByText('Simulated self-transfer completed.')
    const posts = mock.mock.calls.filter(([url]) => url.endsWith('/payments/self-transfer'))
    expect(posts).toHaveLength(2)
    expect(posts[0][1]?.headers).toEqual(posts[1][1]?.headers)
    expect(posts[0][1]?.body).toBe(posts[1][1]?.body)
    expect(balance).toHaveBeenCalledOnce()
    expect(screen.getByRole('article', { name: 'Payment receipt' }).textContent).toContain('No change to your combined funds')
  })

  it('adds an account and preserves the original balance and identifiers', async () => {
    let added = false
    setup((url, init) => {
      if (url.endsWith('/accounts') && init?.method === 'POST') { added = true; return Promise.resolve(json(b, 201)) }
      if (url.endsWith('/accounts')) return Promise.resolve(json(added ? [a,b] : [a]))
    })
    render(<AccountPanel token="token" view="account" onLogout={vi.fn()} />)
    await screen.findByRole('form', { name: 'Add simulated bank account' })
    fireEvent.change(screen.getByLabelText('Demo bank'), { target: { value: b.bank_name } })
    fireEvent.submit(screen.getByRole('form', { name: 'Add simulated bank account' }))
    await waitFor(() => expect(screen.getAllByRole('article', { name: 'Simulated bank account' })).toHaveLength(2))
    expect(screen.getByText('₹1,000.00')).toBeTruthy()
    expect(screen.getByText('₹0.00')).toBeTruthy()
    expect(screen.getByText(a.upi_id)).toBeTruthy()
  })

  it('sets primary through the authenticated API and refreshes all account cards', async () => {
    let switched = false
    const mock = setup((url, init) => {
      if (url.endsWith('/primary') && init?.method === 'PATCH') { switched = true; return Promise.resolve(json({ ...b, is_primary: true })) }
      if (url.endsWith('/accounts')) return Promise.resolve(json(switched ? [{ ...b, is_primary: true }, { ...a, is_primary: false }] : [a,b]))
    })
    render(<AccountPanel token="token" view="account" onLogout={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Set as primary account' }))
    await screen.findByText('Primary account updated. Existing UPI destinations are unchanged.')
    const primary = mock.mock.calls.find(([url]) => url.endsWith('/primary'))!
    expect(primary[1]?.method).toBe('PATCH')
    expect(screen.getByText(a.upi_id)).toBeTruthy()
    expect(screen.getByText('₹1,000.00')).toBeTruthy()
  })

  it('locks source selection after an unknown funding outcome and keeps the selected funding account', async () => {
    const mock = setup((url) => url.endsWith('/demo/fund') ? Promise.reject(new TypeError('Unknown outcome')) : undefined)
    render(<AccountPanel token="token" view="home" onLogout={vi.fn()} />)
    const source = await screen.findByLabelText('Source account') as HTMLSelectElement
    fireEvent.change(source, { target: { value: b.id } })
    fireEvent.click(screen.getByRole('button', { name: 'Add ₹1,000 demo funds' }))
    await screen.findByText('Keep this payment request.')
    await waitFor(() => expect(source.disabled).toBe(true))
    const request = mock.mock.calls.find(([url]) => url.endsWith('/demo/fund'))!
    expect(JSON.parse(String(request[1]?.body))).toEqual({ account_id: b.id })
  })

  it('shows self-transfer history with no income/spending sign and both masked accounts', () => {
    render(<PaymentHistory items={[receipt]} loading={false} error="" busy={false} cursor={null} preview={false} onRefresh={vi.fn()} onMore={vi.fn()} onReceipt={vi.fn()} />)
    expect(screen.getByText('SELF TRANSFER · SUCCESS')).toBeTruthy()
    expect(screen.getByText('₹700.00')).toBeTruthy()
    expect(screen.queryByText('+₹700.00')).toBeNull()
    expect(screen.getByText(/1111.*4444/)).toBeTruthy()
  })

  it('keeps a reviewed transfer pinned to its source if the default account changes', async () => {
    const mock = setup()
    const props = { token: 'token', accountId: 1, sourceAccountId: 1, senderAccount: a, accounts: [a,b], view: 'send' as const, onLogout: vi.fn(), onBalanceChanged: vi.fn().mockResolvedValue(undefined) }
    const view = render(<PaymentPanel {...props} />)
    fireEvent.change(screen.getByLabelText('Recipient UPI ID'), { target: { value: ravi.upi_id } })
    fireEvent.submit(screen.getByRole('form', { name: 'Find payment recipient' }))
    await screen.findByLabelText('Amount · INR')
    fireEvent.change(screen.getByLabelText('Amount · INR'), { target: { value: '50.00' } })
    fireEvent.submit(screen.getByRole('form', { name: 'Send simulated money' }))
    await screen.findByText('Confirm your simulated payment')
    view.rerender(<PaymentPanel {...props} sourceAccountId={4} senderAccount={b} />)
    expect(screen.getByText(/From Grove Demo Bank/).textContent).toContain('1111')
    fireEvent.click(screen.getByRole('button', { name: 'Confirm and send ₹50.00' }))
    await screen.findByText('Simulated payment completed.')
    const call = mock.mock.calls.find(([url]) => url.endsWith('/payments/transfer'))!
    expect(JSON.parse(String(call[1]?.body)).source_account_id).toBe(1)
  })
})
