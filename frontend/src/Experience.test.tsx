import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import App from './App'
import PaymentPanel from './PaymentPanel'
import PaymentHistory from './PaymentHistory'
import { formatMoney } from './formatMoney'
import type { PaymentReceipt } from './api'

const user = { id: 1, full_name: 'Asha Learner', email: 'asha@example.com', created_at: '2026-11-03T10:00:00Z' }
const account = { id: 3, bank_name: 'Grove Demo Bank', masked_account_number: 'SIM •••• 1234', upi_id: 'asha@payflow', balance: '1000.00', created_at: user.created_at }
const recipient = { display_name: 'Verified Ravi', bank_name: 'Orbit Demo Bank', upi_id: 'ravi@payflow' }
const payment: PaymentReceipt = { transaction_id: 'receipt-1', type: 'TRANSFER', direction: 'OUTGOING', status: 'SUCCESS', amount: '125.50', currency: 'INR', counterparty_name: recipient.display_name, counterparty_upi_id: recipient.upi_id, recipient_upi_id: recipient.upi_id, note: '', failure_reason: null, created_at: user.created_at }
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

async function login() {
  fireEvent.change(screen.getByLabelText('Email address'), { target: { value: user.email } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'Learning-password!' } })
  fireEvent.submit(screen.getByRole('form', { name: 'Sign in' }))
  await screen.findByRole('heading', { name: 'Welcome, Asha.' })
  await screen.findByText('₹1,000.00')
}

function setup() {
  const mock = vi.fn(async (url: string) => {
    if (url.includes('/payment-requests/')) return json({ items: [], next_cursor: null, pending_count: 0 })
    if (url.includes('/contacts')) return json([])
    if (url.endsWith('/login')) return json({ access_token: 'memory-token', token_type: 'bearer', expires_in: 900 })
    if (url.endsWith('/me')) return json(user)
    if (url.endsWith('/banks')) return json(['Grove Demo Bank'])
    if (url.endsWith('/accounts')) return json([account])
    if (url.includes('/history')) return json({ items: [payment], next_cursor: null })
    if (url.endsWith('/resolve')) return json(recipient)
    return json(payment, 201)
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

describe('Phase 6 experience', () => {
  it('toggles password visibility without submitting and resets visibility between forms', () => {
    setup()
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Show password' }))
    expect(screen.getByLabelText('Password').getAttribute('type')).toBe('text')
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(screen.getByLabelText('Password').getAttribute('type')).toBe('password')
    fireEvent.click(screen.getByRole('button', { name: 'Show confirm password' }))
    expect(screen.getByLabelText('Confirm password').getAttribute('type')).toBe('text')
  })

  it('navigates between dashboard, account, history and profile without another login', async () => {
    const mock = setup()
    render(<App />)
    await login()
    const nav = screen.getByRole('navigation', { name: 'Main navigation' })
    expect(within(nav).getByRole('button', { name: 'Home' }).getAttribute('aria-current')).toBe('page')
    expect(screen.getByRole('heading', { name: 'Recent activity' })).toBeTruthy()
    fireEvent.click(within(nav).getByRole('button', { name: 'Transactions' }))
    expect(screen.getByRole('heading', { name: 'Payment history' })).toBeTruthy()
    fireEvent.click(within(nav).getByRole('button', { name: 'My Bank Accounts' }))
    expect(screen.getByRole('article', { name: 'Simulated bank account' })).toBeTruthy()
    fireEvent.click(within(nav).getByRole('button', { name: 'Profile' }))
    expect(screen.getByRole('heading', { name: 'Your profile' })).toBeTruthy()
    expect(screen.getByText(user.email)).toBeTruthy()
    expect(mock.mock.calls.filter(([url]) => url.endsWith('/login'))).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'Log out' }))
    expect(screen.queryByRole('navigation')).toBeNull()
    expect(screen.queryByText(account.upi_id)).toBeNull()
  })

  it('verifies a direct recipient before amount entry and requires explicit confirmation', async () => {
    const mock = setup()
    render(<App />)
    await login()
    fireEvent.click(within(screen.getByRole('navigation')).getByRole('button', { name: 'Send Money' }))
    expect(screen.queryByLabelText('Amount · INR')).toBeNull()
    fireEvent.change(screen.getByLabelText('Recipient UPI ID'), { target: { value: recipient.upi_id } })
    fireEvent.submit(screen.getByRole('form', { name: 'Find payment recipient' }))
    await screen.findByText('Verified recipient: Verified Ravi')
    expect((screen.getByLabelText('Recipient UPI ID') as HTMLInputElement).readOnly).toBe(true)
    fireEvent.change(screen.getByLabelText('Amount · INR'), { target: { value: '125.50' } })
    fireEvent.submit(screen.getByRole('form', { name: 'Send simulated money' }))
    await screen.findByText('Confirm your simulated payment')
    expect(mock.mock.calls.some(([url]) => url.endsWith('/transfer'))).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'Confirm and send ₹125.50' }))
    await screen.findByText('Simulated payment completed.')
    expect(screen.getByRole('article', { name: 'Payment receipt' }).textContent).toContain(payment.transaction_id)
  })

  it('keeps an uncertain payment and its original retry key across navigation', async () => {
    let sends = 0
    const mock = setup()
    const base = mock.getMockImplementation()!
    mock.mockImplementation(async (url: string) => {
      if (url.endsWith('/transfer') && ++sends === 1) throw new TypeError('Lost response')
      return base(url)
    })
    render(<App />)
    await login()
    const nav = within(screen.getByRole('navigation'))
    fireEvent.click(nav.getByRole('button', { name: 'Send Money' }))
    fireEvent.change(screen.getByLabelText('Recipient UPI ID'), { target: { value: recipient.upi_id } })
    fireEvent.submit(screen.getByRole('form', { name: 'Find payment recipient' }))
    await screen.findByLabelText('Amount · INR')
    fireEvent.change(screen.getByLabelText('Amount · INR'), { target: { value: '125.50' } })
    fireEvent.submit(screen.getByRole('form', { name: 'Send simulated money' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm and send ₹125.50' }))
    await screen.findByText('Keep this payment request.')
    const saved = sessionStorage.getItem('payflow.pending.3')
    fireEvent.click(nav.getByRole('button', { name: 'Transactions' }))
    fireEvent.click(nav.getByRole('button', { name: 'Scan QR' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    fireEvent.click(nav.getByRole('button', { name: 'Home' }))
    expect(sessionStorage.getItem('payflow.pending.3')).toBe(saved)
    fireEvent.click(screen.getByRole('button', { name: 'Retry same request' }))
    await screen.findByText('Simulated payment completed.')
    const posts = mock.mock.calls.filter(([url]) => url.endsWith('/transfer'))
    expect(posts).toHaveLength(2)
  })

  it('filters loaded history and keeps pagination available when the filter is empty', () => {
    const more = vi.fn()
    render(<PaymentHistory items={[payment]} loading={false} error="" busy={false} cursor="older" preview={false} onRefresh={vi.fn()} onMore={more} onReceipt={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Show transactions'), { target: { value: 'INCOMING' } })
    expect(screen.queryByRole('button', { name: 'View receipt receipt-1' })).toBeNull()
    expect(screen.getByText(/No matching transactions/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Load older payments' }))
    expect(more).toHaveBeenCalledOnce()
  })

  it('reports copy success and clipboard errors accessibly', async () => {
    setup()
    vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } })
    render(<App />)
    await login()
    fireEvent.click(screen.getByRole('button', { name: 'Copy UPI ID' }))
    await screen.findByText('UPI ID copied.')
    vi.mocked(navigator.clipboard.writeText).mockRejectedValueOnce(new Error('Denied'))
    fireEvent.click(screen.getByRole('button', { name: 'Copy UPI ID' }))
    await screen.findByText('Copy unavailable. Select and copy your UPI ID above.')
  })

  it('preserves confirmation when navigating away and returning', async () => {
    setup()
    const props = { token: 'token', accountId: 3, senderAccount: account, onLogout: vi.fn(), onBalanceChanged: vi.fn() }
    const view = render(<PaymentPanel {...props} view="send" />)
    fireEvent.change(screen.getByLabelText('Recipient UPI ID'), { target: { value: recipient.upi_id } })
    fireEvent.submit(screen.getByRole('form', { name: 'Find payment recipient' }))
    await screen.findByLabelText('Amount · INR')
    fireEvent.change(screen.getByLabelText('Amount · INR'), { target: { value: '125.50' } })
    fireEvent.submit(screen.getByRole('form', { name: 'Send simulated money' }))
    await screen.findByText('Confirm your simulated payment')
    view.rerender(<PaymentPanel {...props} view="transactions" />)
    expect(screen.queryByRole('button', { name: 'Confirm and send ₹125.50' })).toBeNull()
    view.rerender(<PaymentPanel {...props} view="send" />)
    expect(screen.getByRole('button', { name: 'Confirm and send ₹125.50' })).toBeTruthy()
    await act(async () => {})
  })

  it('formats very large exact decimal balances without floating-point rounding', () => {
    expect(formatMoney('9999999999999999.99')).toBe('₹9,99,99,99,99,99,99,999.99')
    expect(formatMoney('0.01')).toBe('₹0.01')
  })

  it('shows navigation focus and the current destination for keyboard users', async () => {
    setup()
    render(<App />)
    await login()
    const button = within(screen.getByRole('navigation')).getByRole('button', { name: 'Transactions' })
    fireEvent.click(button)
    expect(button.getAttribute('aria-current')).toBe('page')
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Transactions' })))
    expect(screen.getByRole('link', { name: 'Skip to content' }).getAttribute('href')).toBe('#dashboard-content')
  })
})
