import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import PaymentPanel from './PaymentPanel'
import type { PaymentReceipt } from './api'

const recipient = { display_name: 'Recipient Learner', bank_name: 'River Demo Bank', upi_id: 'recipient-123@payflow' }
const sender = { bank_name: 'Orbit Demo Bank', masked_account_number: 'SIM •••• 9440', upi_id: 'sender@payflow', balance: '2000.00' }
const receipt: PaymentReceipt = {
  transaction_id: 'payment-test-id', type: 'TRANSFER', direction: 'OUTGOING', status: 'SUCCESS',
  amount: '12.30', currency: 'INR', counterparty_name: recipient.display_name,
  counterparty_upi_id: recipient.upi_id, recipient_upi_id: recipient.upi_id,
  note: 'Lunch', failure_reason: null, created_at: '2026-11-03T10:00:00Z',
}
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function setup(handler?: (url: string, options?: RequestInit) => Promise<Response>) {
  const mock = vi.fn(async (url: string, options?: RequestInit) => {
    if (handler) return handler(url, options)
    if (url.includes('/payments/history')) return json({ items: [], next_cursor: null })
    if (url.endsWith('/payments/resolve')) return json(recipient)
    if (url.endsWith('/demo/fund')) return json({ ...receipt, type: 'DEMO_FUNDING', direction: 'FUNDING', amount: '1000.00' }, 201)
    return json(receipt, 201)
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

function fillForm(amount = '12.3') {
  fireEvent.change(screen.getByLabelText('Recipient UPI ID'), { target: { value: recipient.upi_id } })
  fireEvent.change(screen.getByLabelText('Amount · INR'), { target: { value: amount } })
  fireEvent.change(screen.getByLabelText('Note · optional'), { target: { value: 'Lunch' } })
}

async function review() {
  fillForm()
  fireEvent.submit(screen.getByRole('form', { name: 'Send simulated money' }))
  await screen.findByText('Confirm your simulated payment')
}

describe('Simulated payments', () => {
  it.each(['30000', '2000.01'])('blocks an unaffordable amount %s before lookup or confirmation', async (amount) => {
    const mock = setup()
    render(<PaymentPanel accountId={3} token="token" senderAccount={sender} onLogout={vi.fn()} onBalanceChanged={vi.fn()} />)
    fillForm(amount)
    fireEvent.submit(screen.getByRole('form', { name: 'Send simulated money' }))
    await screen.findByText('Insufficient simulated funds. Available balance: ₹2,000.00.')
    expect(screen.queryByText('Confirm your simulated payment')).toBeNull()
    expect(mock.mock.calls.some(([url]) => url.endsWith('/resolve') || url.endsWith('/transfer'))).toBe(false)
  })

  it('allows spending the exact balance and disables confirmation if the balance later drops', async () => {
    const mock = setup()
    const props = { accountId: 3, token: 'token', onLogout: vi.fn(), onBalanceChanged: vi.fn() }
    const view = render(<PaymentPanel {...props} senderAccount={sender} />)
    fillForm('2000.00')
    fireEvent.submit(screen.getByRole('form', { name: 'Send simulated money' }))
    const button = await screen.findByRole('button', { name: 'Confirm and send ₹2,000.00' }) as HTMLButtonElement
    expect(button.disabled).toBe(false)
    view.rerender(<PaymentPanel {...props} senderAccount={{ ...sender, balance: '1999.99' }} />)
    expect(button.disabled).toBe(true)
    fireEvent.click(button)
    expect(mock.mock.calls.some(([url]) => url.endsWith('/transfer'))).toBe(false)
    expect(screen.getByRole('alert').textContent).toContain('₹1,999.99')
  })

  it('retries an uncertain transfer with the same key even after the displayed balance drops', async () => {
    let sends = 0
    const mock = setup(async (url) => {
      if (url.includes('/history')) return json({ items: [], next_cursor: null })
      if (url.endsWith('/resolve')) return json(recipient)
      if (++sends === 1) throw new TypeError('Response lost')
      return json(receipt, 201)
    })
    const props = { accountId: 3, token: 'token', onLogout: vi.fn(), onBalanceChanged: vi.fn().mockResolvedValue(undefined) }
    const view = render(<PaymentPanel {...props} senderAccount={sender} />)
    await review()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm and send ₹12.30' }))
    await screen.findByText('Keep this payment request.')
    view.rerender(<PaymentPanel {...props} senderAccount={{ ...sender, balance: '0.00' }} />)
    fireEvent.click(screen.getByRole('button', { name: 'Retry same request' }))
    await screen.findByText('Simulated payment completed.')
    const requests = mock.mock.calls.filter(([url]) => url.endsWith('/transfer'))
    expect(requests).toHaveLength(2)
    expect(requests[0][1]?.headers).toEqual(requests[1][1]?.headers)
    expect(requests[0][1]?.body).toEqual(requests[1][1]?.body)
  })

  it('restores the original pending request after remount and never stores the JWT', async () => {
    let calls = 0
    const mock = setup(async (url) => {
      if (url.includes('/history')) return json({ items: [], next_cursor: null })
      if (++calls === 1) throw new TypeError('Response lost')
      return json({ ...receipt, type: 'DEMO_FUNDING', direction: 'FUNDING' }, 201)
    })
    const view = render(<PaymentPanel accountId={3} token="secret-jwt" onLogout={vi.fn()} onBalanceChanged={vi.fn().mockResolvedValue(undefined)} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add ₹1,000 demo funds' }))
    await screen.findByText('Keep this payment request.')
    const stored = sessionStorage.getItem('payflow.pending.3')!
    expect(stored).not.toContain('secret-jwt')
    view.unmount()
    render(<PaymentPanel accountId={3} token="new-jwt" onLogout={vi.fn()} onBalanceChanged={vi.fn().mockResolvedValue(undefined)} />)
    fireEvent.click(screen.getByRole('button', { name: 'Retry same request' }))
    await screen.findByText('Simulated funds added successfully.')
    const requests = mock.mock.calls.filter(([url]) => url.endsWith('/demo/fund'))
    expect((requests[0][1]?.headers as Record<string, string>)['Idempotency-Key']).toBe((requests[1][1]?.headers as Record<string, string>)['Idempotency-Key'])
    expect(sessionStorage.getItem('payflow.pending.3')).toBeNull()
  })

  it('does not send money when the retry key cannot be saved safely', async () => {
    const mock = setup()
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Storage unavailable') })
    render(<PaymentPanel accountId={3} token="token" onLogout={vi.fn()} onBalanceChanged={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add ₹1,000 demo funds' }))
    await screen.findByText('Cannot save the retry key in this tab. Enable browser session storage before sending.')
    expect(mock.mock.calls.filter(([url]) => url.endsWith('/demo/fund'))).toHaveLength(0)
  })

  it('loads the empty history state and funds exactly ₹1,000 with a request key', async () => {
    const mock = setup()
    const balance = vi.fn().mockResolvedValue(undefined)
    render(<PaymentPanel accountId={3} token="token" onLogout={vi.fn()} onBalanceChanged={balance} />)
    await screen.findByText('No payments yet. Add demo funds to get started.')
    fireEvent.click(screen.getByRole('button', { name: 'Add ₹1,000 demo funds' }))
    await screen.findByText('Simulated funds added successfully.')
    expect(screen.getByRole('article', { name: 'Payment receipt' }).textContent).toContain('1,000.00')
    const request = mock.mock.calls.find(([url]) => url.endsWith('/demo/fund'))!
    expect(request[1]?.body).toBe('{}')
    expect((request[1]?.headers as Record<string, string>)['Idempotency-Key']).toBeTruthy()
    expect(balance).toHaveBeenCalledTimes(1)
  })

  it('resolves the exact recipient, confirms amount, then sends once and shows a receipt', async () => {
    const mock = setup()
    const balance = vi.fn().mockResolvedValue(undefined)
    render(<PaymentPanel accountId={3} token="token" onLogout={vi.fn()} onBalanceChanged={balance} />)
    await review()
    expect(screen.getByText(recipient.display_name)).toBeTruthy()
    expect(mock.mock.calls.filter(([url]) => url.endsWith('/payments/transfer'))).toHaveLength(0)
    fireEvent.click(screen.getByRole('button', { name: 'Confirm and send ₹12.30' }))
    await screen.findByText('Simulated payment completed.')
    const sent = mock.mock.calls.find(([url]) => url.endsWith('/payments/transfer'))!
    expect(JSON.parse(String(sent[1]?.body))).toEqual({ upi_id: recipient.upi_id, amount: '12.30', note: 'Lunch' })
    const view = screen.getByRole('article', { name: 'Payment receipt' })
    expect(view.textContent).toContain('SUCCESS')
    expect(view.textContent).toContain(receipt.transaction_id)
    expect(balance).toHaveBeenCalledTimes(1)
  })

  it('rejects zero and overprecision before lookup', async () => {
    const mock = setup()
    render(<PaymentPanel accountId={3} token="token" onLogout={vi.fn()} onBalanceChanged={vi.fn()} />)
    for (const value of ['0', '-1', '1.001', '100000.01']) {
      fillForm(value)
      fireEvent.submit(screen.getByRole('form', { name: 'Send simulated money' }))
    }
    expect(mock.mock.calls.some(([url]) => url.endsWith('/payments/resolve'))).toBe(false)
  })

  it('shows recipient lookup failures without starting a money request', async () => {
    const mock = setup(async (url) => url.includes('/history') ? json({ items: [], next_cursor: null }) : json({ detail: 'Recipient not available' }, 404))
    render(<PaymentPanel accountId={3} token="token" onLogout={vi.fn()} onBalanceChanged={vi.fn()} />)
    fillForm()
    fireEvent.submit(screen.getByRole('form', { name: 'Send simulated money' }))
    await screen.findByText('Recipient not available')
    expect(mock.mock.calls.some(([url]) => url.endsWith('/payments/transfer'))).toBe(false)
  })

  it('preserves the exact key and payload when a transfer outcome is unknown', async () => {
    let sends = 0
    const mock = setup(async (url) => {
      if (url.includes('/history')) return json({ items: [], next_cursor: null })
      if (url.endsWith('/resolve')) return json(recipient)
      if (++sends === 1) throw new TypeError('Network unavailable')
      return json(receipt, 201)
    })
    render(<PaymentPanel accountId={3} token="token" onLogout={vi.fn()} onBalanceChanged={vi.fn().mockResolvedValue(undefined)} />)
    await review()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm and send ₹12.30' }))
    await screen.findByText('Keep this payment request.')
    expect((screen.getByRole('button', { name: 'Add ₹1,000 demo funds' }) as HTMLButtonElement).disabled).toBe(true)
    expect(sends).toBe(1)
    fireEvent.click(screen.getByRole('button', { name: 'Retry same request' }))
    await screen.findByText('Simulated payment completed.')
    const requests = mock.mock.calls.filter(([url]) => url.endsWith('/transfer'))
    expect(requests).toHaveLength(2)
    expect(requests[0][1]?.body).toBe(requests[1][1]?.body)
    expect(requests[0][1]?.headers).toEqual(requests[1][1]?.headers)
  })

  it('reuses the funding key after a server 503 instead of creating a second action', async () => {
    let calls = 0
    const mock = setup(async (url) => {
      if (url.includes('/history')) return json({ items: [], next_cursor: null })
      if (++calls === 1) return json({ detail: 'Retry with the same key' }, 503)
      return json({ ...receipt, type: 'DEMO_FUNDING', direction: 'FUNDING', amount: '1000.00' }, 201)
    })
    render(<PaymentPanel accountId={3} token="token" onLogout={vi.fn()} onBalanceChanged={vi.fn().mockResolvedValue(undefined)} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add ₹1,000 demo funds' }))
    await screen.findByText('Keep this payment request.')
    fireEvent.click(screen.getByRole('button', { name: 'Retry same request' }))
    await screen.findByText('Simulated funds added successfully.')
    const posts = mock.mock.calls.filter(([url]) => url.endsWith('/demo/fund'))
    expect(posts[0][1]?.headers).toEqual(posts[1][1]?.headers)
  })

  it('shows a failed transfer receipt and restores the editable form for a new intent', async () => {
    setup(async (url) => {
      if (url.includes('/history')) return json({ items: [], next_cursor: null })
      if (url.endsWith('/resolve')) return json(recipient)
      return json({ detail: 'Insufficient simulated funds', receipt: { ...receipt, status: 'FAILED', failure_reason: 'Insufficient simulated funds' } }, 400)
    })
    render(<PaymentPanel accountId={3} token="token" onLogout={vi.fn()} onBalanceChanged={vi.fn()} />)
    await review()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm and send ₹12.30' }))
    await screen.findByText('Insufficient simulated funds')
    expect(screen.getByRole('article', { name: 'Payment receipt' }).textContent).toContain('No funds moved.')
    expect(screen.getByRole('form', { name: 'Send simulated money' })).toBeTruthy()
  })

  it('prevents duplicate confirmation while the request is pending', async () => {
    let resolve!: (value: Response) => void
    const mock = setup(async (url) => {
      if (url.includes('/history')) return json({ items: [], next_cursor: null })
      if (url.endsWith('/resolve')) return json(recipient)
      return new Promise((done) => { resolve = done })
    })
    render(<PaymentPanel accountId={3} token="token" onLogout={vi.fn()} onBalanceChanged={vi.fn().mockResolvedValue(undefined)} />)
    await review()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm and send ₹12.30' }))
    const button = screen.getByRole('button', { name: 'Sending…' }) as HTMLButtonElement
    expect(button.disabled).toBe(true)
    fireEvent.click(button)
    expect(mock.mock.calls.filter(([url]) => url.endsWith('/transfer'))).toHaveLength(1)
    await act(async () => { resolve(json(receipt, 201)) })
    await screen.findByText('Simulated payment completed.')
  })

  it('loads history pages, labels incoming/outgoing, and fetches the selected receipt', async () => {
    setup(async (url) => {
      if (url.includes('?before=')) return json({ items: [{ ...receipt, transaction_id: 'older', direction: 'INCOMING' }], next_cursor: null })
      if (url.includes('/history')) return json({ items: [receipt], next_cursor: receipt.transaction_id })
      return json(receipt)
    })
    render(<PaymentPanel accountId={3} token="token" onLogout={vi.fn()} onBalanceChanged={vi.fn()} />)
    await screen.findByText('OUTGOING · SUCCESS')
    fireEvent.click(screen.getByRole('button', { name: 'Load older payments' }))
    await screen.findByText('INCOMING · SUCCESS')
    fireEvent.click(screen.getByRole('button', { name: `View receipt ${receipt.transaction_id}` }))
    const view = await screen.findByRole('article', { name: 'Payment receipt' })
    expect(within(view).getByText(/payment-test-id/)).toBeTruthy()
  })

  it('handles history failures and logs out on expired authorization', async () => {
    let expired = false
    const logout = vi.fn()
    setup(async () => json({ detail: expired ? 'Expired' : 'Database unavailable' }, expired ? 401 : 503))
    render(<PaymentPanel accountId={3} token="token" onLogout={logout} onBalanceChanged={vi.fn()} />)
    await screen.findByRole('alert')
    expired = true
    fireEvent.click(screen.getByRole('button', { name: 'Refresh history' }))
    await waitFor(() => expect(logout).toHaveBeenCalled())
  })

  it('does not revive a receipt or refresh a logged-out account after unmount', async () => {
    let resolve!: (value: Response) => void
    const balance = vi.fn()
    setup(async (url) => url.includes('/history') ? json({ items: [], next_cursor: null }) : new Promise((done) => { resolve = done }))
    const view = render(<PaymentPanel accountId={3} token="token" onLogout={vi.fn()} onBalanceChanged={balance} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add ₹1,000 demo funds' }))
    view.unmount()
    const newer = { key: crypto.randomUUID(), kind: 'fund', uncertain: true }
    sessionStorage.setItem('payflow.pending.3', JSON.stringify(newer))
    await act(async () => { resolve(json(receipt, 201)) })
    expect(screen.queryByRole('article', { name: 'Payment receipt' })).toBeNull()
    expect(balance).not.toHaveBeenCalled()
    expect(JSON.parse(sessionStorage.getItem('payflow.pending.3')!).key).toBe(newer.key)
  })
})
