import { useState } from 'react'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import SocialPanel from './SocialPanel'
import PaymentPanel from './PaymentPanel'
import type { DashboardView } from './navigation'

const person = { display_name: 'Ravi Learner', upi_id: 'ravi@payflow' }
const owner = { display_name: 'Asha Learner', upi_id: 'asha@payflow' }
const senderAccount = { bank_name: 'Grove Demo Bank', masked_account_number: 'SIM •••• 1234', upi_id: owner.upi_id, balance: '1000.00' }
const contact = { ...person, id: 'contact-one', is_favorite: false, created_at: '2026-11-04T00:00:00Z', updated_at: '2026-11-04T00:00:00Z' }
const request = { id: 'f7c27905-d900-4fb2-a251-6bcaf8aecf25', requester: person, payer: owner, amount: '125.50', note: 'Lunch', status: 'PENDING', payment_id: null as string | null, created_at: '2026-11-04T00:00:00Z', updated_at: '2026-11-04T00:00:00Z', expires_at: '2030-11-11T00:00:00Z' }
const receipt = { transaction_id: 'paid-receipt', type: 'TRANSFER', direction: 'OUTGOING', status: 'SUCCESS', amount: '125.50', currency: 'INR', counterparty_name: person.display_name, counterparty_upi_id: person.upi_id, recipient_upi_id: person.upi_id, note: 'Lunch', failure_reason: null, created_at: '2026-11-04T00:00:00Z' }
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })

function setup(options: { saved?: boolean; pending?: boolean; recent?: boolean; override?: (url: string, init?: RequestInit) => Promise<Response> | undefined } = {}) {
  let saved = options.saved ? [contact] : []
  let incoming = options.pending ? [{ ...request }] : []
  let outgoing: typeof incoming = []
  const mock = vi.fn(async (url: string, init?: RequestInit): Promise<Response> => {
    const custom = options.override?.(url, init)
    if (custom) return custom
    if (url.endsWith('/contacts/recent')) return json(options.recent ? [{ ...person, last_interacted_at: request.created_at }] : [])
    if (url.endsWith('/contacts') && init?.method === 'POST') { saved = [contact]; return json(contact, 201) }
    if (url.endsWith('/contacts')) return json(saved)
    if (url.endsWith('/favorite')) { saved = [{ ...contact, is_favorite: JSON.parse(String(init?.body)).is_favorite }]; return json(saved[0]) }
    if (init?.method === 'DELETE') { saved = []; return new Response(null, { status: 204 }) }
    if (url.includes('/payment-requests/incoming')) return json({ items: incoming, next_cursor: null, pending_count: incoming.filter((item) => item.status === 'PENDING').length })
    if (url.includes('/payment-requests/outgoing')) return json({ items: outgoing, next_cursor: null, pending_count: outgoing.filter((item) => item.status === 'PENDING').length })
    if (url.endsWith('/payments/resolve')) return json({ ...person, bank_name: 'Orbit Demo Bank' })
    if (url.endsWith('/payment-requests') && init?.method === 'POST') { outgoing = [{ ...request, requester: owner, payer: person }]; return json(outgoing[0], 201) }
    if (url.endsWith('/decline') || url.endsWith('/cancel')) { incoming = [{ ...request, status: 'DECLINED' }]; outgoing = [{ ...request, requester: owner, payer: person, status: 'CANCELLED' }]; return json(url.endsWith('/cancel') ? outgoing[0] : incoming[0]) }
    if (url.endsWith('/pay')) { incoming = [{ ...request, status: 'PAID', payment_id: receipt.transaction_id }]; return json(receipt, 201) }
    if (url.includes('/payment-requests/')) return json(request)
    if (url.includes('/payments/history')) return json({ items: [], next_cursor: null })
    return json(receipt)
  })
  vi.stubGlobal('fetch', mock)
  return mock
}
function panel(view: DashboardView = 'contacts', overrides = {}) {
  const props = { token: 'memory-token', accountId: 3, view, revision: 0, locked: false, senderAccount, onNavigate: vi.fn(), onLogout: vi.fn(), onSend: vi.fn().mockResolvedValue(undefined), onPay: vi.fn().mockResolvedValue(undefined), onReceipt: vi.fn().mockResolvedValue(undefined), ...overrides }
  return { ...render(<SocialPanel {...props} />), props }
}
async function search() {
  fireEvent.change(screen.getByLabelText('UPI ID to find'), { target: { value: person.upi_id } })
  fireEvent.submit(screen.getByRole('form', { name: 'Find PayFlow user' }))
  await screen.findByText('Verified: Ravi Learner')
}

describe('Phase 7 contacts and requests', () => {
  it('searches exact UPI, shows only verified public details, and saves a personal contact', async () => {
    const mock = setup()
    panel()
    await search()
    fireEvent.click(screen.getByRole('button', { name: 'Add to saved contacts' }))
    await screen.findByText('Contact saved to your personal address book.')
    expect(screen.getByText(/Saved contacts are personal/)).toBeTruthy()
    expect(mock.mock.calls.find(([url]) => url.endsWith('/resolve'))?.[1]?.body).toBe(JSON.stringify({ upi_id: person.upi_id }))
    expect(mock.mock.calls.filter(([url, init]) => url.endsWith('/contacts') && init?.method === 'POST')).toHaveLength(1)
  })

  it('favorites and unfavorites a saved contact', async () => {
    setup({ saved: true })
    panel()
    fireEvent.click(await screen.findByRole('button', { name: 'Favorite Ravi Learner' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Unfavorite Ravi Learner' }))
    await screen.findByRole('button', { name: 'Favorite Ravi Learner' })
  })

  it('opens a public contact profile and confirms removal before deleting only the contact', async () => {
    const mock = setup({ saved: true })
    const { props } = panel()
    fireEvent.click(await screen.findByRole('button', { name: 'Open contact Ravi Learner' }))
    expect(screen.getByRole('region', { name: 'Contact profile' })).toBeTruthy()
    fireEvent.click(within(screen.getByRole('region', { name: 'Contact profile' })).getByRole('button', { name: 'Send Money' }))
    expect(props.onSend).toHaveBeenCalledWith(person.upi_id)
    fireEvent.click(within(screen.getByRole('region', { name: 'Contact profile' })).getByRole('button', { name: 'Request Money' }))
    expect(props.onNavigate).toHaveBeenCalledWith('request')
    fireEvent.click(screen.getByRole('button', { name: 'Remove contact' }))
    const dialog = screen.getByRole('dialog', { name: 'Remove saved contact?' })
    expect(mock.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)
    fireEvent.click(within(dialog).getByRole('button', { name: 'Remove contact' }))
    await screen.findByText('Contact removed from your address book.')
  })

  it('shows recent contacts and pending incoming shortcut on Home', async () => {
    setup({ recent: true, pending: true })
    const { props } = panel('home')
    fireEvent.click(await screen.findByRole('button', { name: 'Send money to Ravi Learner' }))
    expect(props.onSend).toHaveBeenCalledWith(person.upi_id)
    fireEvent.click(screen.getByRole('button', { name: '1 pending incoming requests' }))
    expect(props.onNavigate).toHaveBeenCalledWith('requests')
  })

  it('creates a request only after verified recipient, amount and review, without a transfer', async () => {
    const mock = setup()
    const { props } = panel('request')
    await search()
    fireEvent.change(screen.getByLabelText('Requested amount · INR'), { target: { value: '125.50' } })
    fireEvent.change(screen.getByLabelText('Request note · optional'), { target: { value: 'Lunch' } })
    fireEvent.submit(screen.getByRole('form', { name: 'Enter money request' }))
    expect(mock.mock.calls.some(([url, init]) => url.endsWith('/payment-requests') && init?.method === 'POST')).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'Send money request' }))
    await screen.findByText('Request sent. No money moved.')
    const call = mock.mock.calls.find(([url, init]) => url.endsWith('/payment-requests') && init?.method === 'POST')!
    expect(JSON.parse(String(call[1]?.body))).toEqual({ upi_id: person.upi_id, amount: '125.50', note: 'Lunch' })
    expect(props.onNavigate).toHaveBeenCalledWith('requests')
    expect(mock.mock.calls.some(([url]) => url.endsWith('/transfer') || url.endsWith('/pay'))).toBe(false)
  })

  it('rejects overprecision and zero when composing requests', async () => {
    setup()
    panel('request')
    await search()
    for (const amount of ['0', '1.001', '100000.01']) {
      fireEvent.change(screen.getByLabelText('Requested amount · INR'), { target: { value: amount } })
      fireEvent.submit(screen.getByRole('form', { name: 'Enter money request' }))
      expect(screen.getByRole('alert')).toBeTruthy()
      expect(screen.queryByRole('button', { name: 'Send money request' })).toBeNull()
    }
  })

  it('preserves the creation key and payload after a lost response and remount', async () => {
    let creates = 0
    const mock = setup({ override: (url, init) => {
      if (url.endsWith('/payment-requests') && init?.method === 'POST' && ++creates === 1) return Promise.reject(new TypeError('Response lost'))
    } })
    const view = panel('request')
    await search()
    fireEvent.change(screen.getByLabelText('Requested amount · INR'), { target: { value: '125.50' } })
    fireEvent.submit(screen.getByRole('form', { name: 'Enter money request' }))
    fireEvent.click(screen.getByRole('button', { name: 'Send money request' }))
    await screen.findByText(/Request creation outcome unknown/)
    expect(sessionStorage.getItem('payflow.collect-create.3')).not.toContain('memory-token')
    view.unmount()
    panel('request')
    fireEvent.click(screen.getByRole('button', { name: 'Retry same request creation' }))
    await screen.findByText('Request sent. No money moved.')
    const posts = mock.mock.calls.filter(([url, init]) => url.endsWith('/payment-requests') && init?.method === 'POST')
    expect(posts[0][1]?.headers).toEqual(posts[1][1]?.headers)
    expect(posts[0][1]?.body).toBe(posts[1][1]?.body)
  })

  it('requires explicit payment confirmation with verified requester and sender details', async () => {
    setup({ pending: true })
    const { props } = panel('requests')
    fireEvent.click(await screen.findByRole('button', { name: 'Pay request' }))
    const dialog = await screen.findByRole('dialog', { name: 'Confirm request payment' })
    expect(dialog.textContent).toContain(senderAccount.masked_account_number)
    expect(dialog.textContent).toContain('₹125.50')
    expect(props.onPay).not.toHaveBeenCalled()
    const back = within(dialog).getByRole('button', { name: 'Go back' })
    const confirm = within(dialog).getByRole('button', { name: 'Confirm and pay request' })
    back.focus()
    fireEvent.keyDown(dialog, { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(confirm)
    fireEvent.keyDown(dialog, { key: 'Tab' })
    expect(document.activeElement).toBe(back)
    fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm and pay request' }))
    await waitFor(() => expect(props.onPay).toHaveBeenCalledOnce())
  })

  it('declines incoming requests only after confirmation and refreshes their status', async () => {
    const mock = setup({ pending: true })
    panel('requests')
    fireEvent.click(await screen.findByRole('button', { name: 'Decline request' }))
    expect(mock.mock.calls.some(([url]) => url.endsWith('/decline'))).toBe(false)
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm decline' }))
    await screen.findByText('DECLINED')
    expect(screen.queryByRole('button', { name: 'Pay request' })).toBeNull()
  })

  it('switches to outgoing requests and cancels with confirmation', async () => {
    setup({ override: (url) => url.includes('/payment-requests/outgoing') ? Promise.resolve(json({ items: [{ ...request, requester: owner, payer: person }], next_cursor: null, pending_count: 1 })) : undefined })
    panel('requests')
    fireEvent.click(await screen.findByRole('button', { name: 'Outgoing (1)' }))
    fireEvent.click(screen.getByRole('button', { name: 'Cancel request' }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm cancellation' }))
    await screen.findByText('Request cancelled. No money moved.')
  })

  it('handles empty, loading, lookup error and expired authorization states', async () => {
    const mock = setup({ override: (url) => url.endsWith('/resolve') ? Promise.resolve(json({ detail: 'Recipient not available' }, 404)) : undefined })
    const { props } = panel()
    expect(screen.getByText('Loading contacts and requests…')).toBeTruthy()
    await screen.findByText(/No saved contacts yet/)
    fireEvent.change(screen.getByLabelText('UPI ID to find'), { target: { value: person.upi_id } })
    fireEvent.submit(screen.getByRole('form', { name: 'Find PayFlow user' }))
    await screen.findByRole('alert')
    expect(screen.getByRole('alert').textContent).toContain('Recipient not available')
    mock.mockImplementation(async () => json({ detail: 'Expired' }, 401))
    fireEvent.click(screen.getByRole('button', { name: 'Refresh contacts & requests' }))
    await waitFor(() => expect(props.onLogout).toHaveBeenCalled())
  })

  it('blocks all money actions while another payment is unresolved', async () => {
    setup({ pending: true })
    panel('requests', { locked: true })
    const pay = await screen.findByRole('button', { name: 'Pay request' }) as HTMLButtonElement
    expect(pay.disabled).toBe(true)
  })

  it('posts a request payment through the existing payment panel and refreshes balance/history', async () => {
    const mock = setup({ pending: true })
    const balance = vi.fn().mockResolvedValue(undefined)
    function Flow() {
      const [view, setView] = useState<DashboardView>('requests')
      return <PaymentPanel token="token" accountId={3} senderAccount={senderAccount} view={view} onNavigate={setView} onLogout={vi.fn()} onBalanceChanged={balance} />
    }
    render(<Flow />)
    fireEvent.click(await screen.findByRole('button', { name: 'Pay request' }))
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Confirm and pay request' }))
    await screen.findByText('Simulated payment completed.')
    expect(balance).toHaveBeenCalledOnce()
    const posted = mock.mock.calls.filter(([url]) => url.endsWith('/pay'))
    expect(posted).toHaveLength(1)
    expect(posted[0][1]?.body).toBe('{}')
    expect((await screen.findByRole('article', { name: 'Payment receipt' })).textContent).toContain('paid-receipt')
  })

  it('reuses the request payment key after an unknown network result', async () => {
    let pays = 0
    const mock = setup({ pending: true, override: (url) => url.endsWith('/pay') && ++pays === 1 ? Promise.reject(new TypeError('Lost')) : undefined })
    const element = <PaymentPanel token="token" accountId={3} senderAccount={senderAccount} view="requests" onNavigate={vi.fn()} onLogout={vi.fn()} onBalanceChanged={vi.fn().mockResolvedValue(undefined)} />
    const view = render(element)
    fireEvent.click(await screen.findByRole('button', { name: 'Pay request' }))
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Confirm and pay request' }))
    await screen.findByText('Keep this payment request.')
    view.unmount()
    render(element)
    fireEvent.click(screen.getByRole('button', { name: 'Retry same request' }))
    await screen.findByText('Simulated payment completed.')
    const posts = mock.mock.calls.filter(([url]) => url.endsWith('/pay'))
    expect(posts).toHaveLength(2)
    expect(posts[0][1]?.headers).toEqual(posts[1][1]?.headers)
    expect(posts[0][1]?.body).toBe(posts[1][1]?.body)
  })

  it('keeps an insufficient-funds request pending and available for a later explicit payment', async () => {
    setup({ pending: true, override: (url) => url.endsWith('/pay') ? Promise.resolve(json({ detail: 'Insufficient simulated funds', receipt: { ...receipt, status: 'FAILED', failure_reason: 'Insufficient simulated funds' } }, 400)) : undefined })
    render(<PaymentPanel token="token" accountId={3} senderAccount={senderAccount} view="requests" onNavigate={vi.fn()} onLogout={vi.fn()} onBalanceChanged={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Pay request' }))
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Confirm and pay request' }))
    await screen.findByText('Insufficient simulated funds')
    await waitFor(() => expect((screen.getByRole('button', { name: 'Pay request' }) as HTMLButtonElement).disabled).toBe(false))
    expect(screen.getByText('PENDING')).toBeTruthy()
    expect(sessionStorage.getItem('payflow.pending.3')).toBeNull()
  })
})
