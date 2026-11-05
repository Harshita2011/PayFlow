import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import SecurityPanel from './SecurityPanel'
import PaymentPanel from './PaymentPanel'
import PaymentPinDialog from './PaymentPinDialog'
const status = { pin_configured: false, locked_until: null, remaining_attempts: 5, single_limit: '100000.00', daily_limit: '200000.00', daily_count_limit: 50, daily_amount_used: '0.00', daily_count_used: 0, reset_timezone: 'UTC' }
const receipt = { transaction_id: 'secure-payment', type: 'TRANSFER', direction: 'OUTGOING', status: 'SUCCESS', amount: '12.30', currency: 'INR', counterparty_name: 'Demo Recipient', counterparty_upi_id: 'recipient@payflow', recipient_upi_id: 'recipient@payflow', note: '', failure_reason: null, created_at: '2026-11-05T12:00:00Z' }
const recipient = { display_name: 'Demo Recipient', bank_name: 'Grove Demo Bank', upi_id: 'recipient@payflow' }
const json = (data: unknown, code=200) => new Response(JSON.stringify(data), { status: code })
function setup(override?: (path: string, options?: RequestInit) => Promise<Response> | undefined) {
  const mock = vi.fn(async (url: string, options?: RequestInit) => {
    const path = new URL(url).pathname
    const custom = override?.(path, options)
    if (custom) return custom
    if (path === '/security/status') return json(status)
    if (path === '/security/events') return json({ items: [], next_cursor: null })
    if (path === '/security/pin') return json({ message: 'Payment PIN configured.' }, 201)
    if (path === '/security/pin/change') return json({ message: 'Payment PIN changed.' })
    if (path === '/security/payment-authorizations') return json({ authorization_token: 'private-grant', expires_at: '2099-01-01T00:00:00Z', amount: '12.30', source_account_id: 1 }, 201)
    if (path === '/payments/history') return json({ items: [], next_cursor: null })
    if (path === '/payments/resolve') return json(recipient)
    if (path === '/contacts' || path === '/contacts/recent') return json([])
    if (path.startsWith('/payment-requests/')) return json({ items: [], next_cursor: null, pending_count: 0 })
    return json(receipt, 201)
  })
  vi.stubGlobal('fetch', mock)
  return mock
}
function payment() {
  return render(<PaymentPanel accountId={1} sourceAccountId={1} token="token" senderAccount={{ bank_name: 'Orbit Demo Bank', masked_account_number: 'SIM •••• 1000', upi_id: 'sender@payflow', balance: '1000.00' }} onLogout={vi.fn()} onBalanceChanged={vi.fn()} />)
}
async function review() {
  fireEvent.change(screen.getByLabelText('Recipient UPI ID'), { target: { value: recipient.upi_id } })
  fireEvent.change(screen.getByLabelText('Amount · INR'), { target: { value: '12.30' } })
  fireEvent.submit(screen.getByRole('form', { name: 'Send simulated money' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Confirm and send ₹12.30' }))
  await screen.findByRole('dialog', { name: 'Authorize simulated payment' })
}
function enterPin(value='482951') {
  fireEvent.change(screen.getByLabelText('Payment PIN', { exact: true }), { target: { value } })
  fireEvent.submit(screen.getByRole('form', { name: 'Payment PIN authorization' }))
}
describe('Payment security UI', () => {
  it('sets a PIN with password reauthentication and clears the fields', async () => {
    const mock = setup()
    render(<SecurityPanel token="token" onLogout={vi.fn()} />)
    await screen.findByRole('form', { name: 'Set Payment PIN' })
    fireEvent.change(screen.getByLabelText('Account password'), { target: { value: 'Example-Password-2026!' } })
    fireEvent.change(screen.getByLabelText('New payment PIN'), { target: { value: '482951' } })
    fireEvent.change(screen.getByLabelText('Confirm payment PIN'), { target: { value: '482951' } })
    fireEvent.submit(screen.getByRole('form', { name: 'Set Payment PIN' }))
    await screen.findByText('Payment PIN configured.')
    expect((screen.getByLabelText('New payment PIN') as HTMLInputElement).value).toBe('')
    expect((screen.getByLabelText('Account password') as HTMLInputElement).value).toBe('')
    expect(JSON.parse(String(mock.mock.calls.find(([url]) => url.endsWith('/security/pin'))![1]?.body))).toEqual({ pin: '482951', password: 'Example-Password-2026!' })
    expect(sessionStorage.length).toBe(0)
  })
  it('changes a configured PIN using the current PIN', async () => {
    const mock = setup((path) => path === '/security/status' ? Promise.resolve(json({ ...status, pin_configured: true })) : undefined)
    render(<SecurityPanel token="token" onLogout={vi.fn()} />)
    await screen.findByRole('form', { name: 'Change Payment PIN' })
    fireEvent.change(screen.getByLabelText('Current payment PIN'), { target: { value: '482951' } })
    fireEvent.change(screen.getByLabelText('New payment PIN'), { target: { value: '579248' } })
    fireEvent.change(screen.getByLabelText('Confirm payment PIN'), { target: { value: '579248' } })
    fireEvent.submit(screen.getByRole('form', { name: 'Change Payment PIN' }))
    await screen.findByText('Payment PIN changed.')
    expect(mock.mock.calls.some(([url]) => url.endsWith('/security/pin/change'))).toBe(true)
  })
  it('rejects mismatched confirmation without an API write', async () => {
    const mock = setup(); render(<SecurityPanel token="token" onLogout={vi.fn()} />)
    await screen.findByRole('form', { name: 'Set Payment PIN' })
    fireEvent.change(screen.getByLabelText('New payment PIN'), { target: { value: '482951' } })
    fireEvent.change(screen.getByLabelText('Confirm payment PIN'), { target: { value: '579248' } })
    fireEvent.submit(screen.getByRole('form', { name: 'Set Payment PIN' }))
    expect(screen.getByRole('alert').textContent).toContain('do not match')
    expect(mock.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false)
  })
  it('displays a PIN lockout and UTC limits', async () => {
    setup((path) => path === '/security/status' ? Promise.resolve(json({ ...status, pin_configured: true, locked_until: '2099-01-01T00:00:00Z' })) : undefined)
    render(<SecurityPanel token="token" onLogout={vi.fn()} />)
    expect((await screen.findByRole('alert')).textContent).toContain('temporarily locked')
    expect(screen.getByText(/Resets at 00:00 UTC/)).toBeTruthy()
    expect((screen.getByRole('button', { name: 'Change PIN' }) as HTMLButtonElement).closest('fieldset')?.disabled).toBe(true)
  })
  it('requires masked PIN entry after payment review, then posts a grant header', async () => {
    const mock = setup(); payment(); await review()
    expect(mock.mock.calls.some(([url]) => url.endsWith('/payments/transfer'))).toBe(false)
    expect((screen.getByLabelText('Payment PIN', { exact: true }) as HTMLInputElement).type).toBe('password')
    enterPin(); await screen.findByText('Simulated payment completed.')
    const posted = mock.mock.calls.find(([url]) => url.endsWith('/payments/transfer'))!
    expect((posted[1]?.headers as Record<string, string>)['Payment-Authorization']).toBe('private-grant')
    expect(String(posted[1]?.body)).not.toContain('482951')
    expect(sessionStorage.length).toBe(0)
  })
  it('shows a wrong PIN without sending a payment and clears its input', async () => {
    const mock = setup((path) => path === '/security/payment-authorizations' ? Promise.resolve(json({ detail: 'Incorrect payment PIN.', code: 'PIN_INVALID' }, 400)) : undefined)
    payment(); await review(); enterPin('135790')
    expect((await screen.findByRole('alert')).textContent).toContain('Incorrect payment PIN')
    expect((screen.getByLabelText('Payment PIN', { exact: true }) as HTMLInputElement).value).toBe('')
    expect(mock.mock.calls.some(([url]) => url.endsWith('/payments/transfer'))).toBe(false)
  })
  it('shows lockout errors and does not mislabel them as session expiry', async () => {
    setup((path) => path === '/security/payment-authorizations' ? Promise.resolve(json({ detail: 'Payment PIN is temporarily locked. Try again later.', code: 'PIN_LOCKED' }, 423)) : undefined)
    payment(); await review(); enterPin()
    expect((await screen.findByRole('alert')).textContent).toContain('temporarily locked')
    expect(screen.getByRole('dialog')).toBeTruthy()
  })
  it.each([['LIMIT_EXCEEDED', 'Daily payment limit exceeded.'], ['RISK_BLOCKED', 'Payment blocked by demo security rule: PAYMENT_VELOCITY.']])('renders %s in red with no success receipt', async (code, detail) => {
    setup((path) => path === '/payments/transfer' ? Promise.resolve(json({ code, detail }, 403)) : undefined)
    payment(); await review(); enterPin()
    await screen.findByText(detail)
    expect(screen.queryByRole('article', { name: 'Payment receipt' })).toBeNull()
    expect(screen.getByText(detail).className).toContain('error')
  })
  it('keeps PIN and raw grants out of persisted uncertain intents', async () => {
    setup((path) => path === '/payments/transfer' ? Promise.reject(new Error('lost response')) : undefined)
    payment(); await review(); enterPin()
    await screen.findByText('Keep this payment request.')
    const saved = sessionStorage.getItem('payflow.pending.1')!
    expect(saved).not.toContain('482951'); expect(saved).not.toContain('private-grant')
    expect(JSON.parse(saved).key).toBeTruthy()
  })
  it('recovers a committed result after refresh without persisting the grant', async () => {
    let posts = 0
    const mock = setup((path) => path === '/payments/transfer' && ++posts === 1 ? Promise.reject(new Error('lost response')) : undefined)
    const view = payment(); await review(); enterPin(); await screen.findByText('Keep this payment request.')
    view.unmount(); payment()
    fireEvent.click(screen.getByRole('button', { name: 'Retry same request' }))
    await screen.findByText('Simulated payment completed.')
    const submitted = mock.mock.calls.filter(([url]) => url.endsWith('/payments/transfer'))
    expect((submitted[0][1]?.headers as Record<string, string>)['Idempotency-Key']).toBe((submitted[1][1]?.headers as Record<string, string>)['Idempotency-Key'])
    expect((submitted[1][1]?.headers as Record<string, string>)['Payment-Authorization']).toBeUndefined()
  })
  it('asks for a fresh grant on an uncommitted retry and preserves the intended key', async () => {
    const key = 'c14994cb-d7d4-4cf4-8c16-2d049e92414d'
    sessionStorage.setItem('payflow.pending.1', JSON.stringify({ key, kind: 'transfer', uncertain: true, payload: { upi_id: recipient.upi_id, source_account_id: 1, amount: '12.30', note: '' } }))
    let calls = 0
    const mock = setup((path) => path === '/payments/transfer' && ++calls === 1 ? Promise.resolve(json({ detail: 'Confirm your PIN.', code: 'PAYMENT_AUTHORIZATION_REQUIRED' }, 403)) : undefined)
    payment(); fireEvent.click(screen.getByRole('button', { name: 'Retry same request' }))
    await screen.findByRole('dialog', { name: 'Authorize simulated payment' }); enterPin()
    await screen.findByText('Simulated payment completed.')
    const posted = mock.mock.calls.filter(([url]) => url.endsWith('/payments/transfer'))
    expect(posted).toHaveLength(2)
    for (const [,options] of posted) expect((options?.headers as Record<string, string>)['Idempotency-Key']).toBe(key)
  })
  it('cleans up the PIN dialog when the authenticated panel unmounts', async () => {
    setup(); const view = payment(); await review()
    fireEvent.change(screen.getByLabelText('Payment PIN', { exact: true }), { target: { value: '482951' } })
    view.unmount()
    expect(screen.queryByRole('dialog')).toBeNull(); expect(sessionStorage.length).toBe(0)
  })
  it('shows missing setup instructions without offering an insecure reset', async () => {
    setup((path) => path === '/security/payment-authorizations' ? Promise.resolve(json({ detail: 'Set a payment PIN in Security Settings before paying.', code: 'PIN_NOT_CONFIGURED' }, 403)) : undefined)
    payment(); await review(); enterPin()
    expect((await screen.findByRole('alert')).textContent).toContain('Security Settings')
    expect(screen.queryByRole('button', { name: /Reset PIN/ })).toBeNull()
  })
  it('validates six-digit input and allows keyboard submission', async () => {
    const submit = vi.fn().mockResolvedValue(undefined)
    render(<PaymentPinDialog busy={false} error="" onSubmit={submit} onClose={vi.fn()} />)
    enterPin('123'); expect(screen.getByRole('alert').textContent).toContain('six-digit')
    expect(submit).not.toHaveBeenCalled()
    enterPin(); await waitFor(() => expect(submit).toHaveBeenCalledWith('482951'))
  })
  it('does not pay when the server-authoritative amount changed after review', async () => {
    const mock = setup((path) => path === '/security/payment-authorizations' ? Promise.resolve(json({ authorization_token: 'private-grant', amount: '99.00', source_account_id: 1 }, 201)) : undefined)
    payment(); await review(); enterPin()
    expect((await screen.findByRole('alert')).textContent).toContain('amount changed')
    expect(mock.mock.calls.some(([url]) => url.endsWith('/payments/transfer'))).toBe(false)
  })
  it('releases the payment lock when pending metadata cannot be saved', async () => {
    const mock = setup(); payment(); await review()
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    enterPin()
    await screen.findByText(/Cannot save the retry key/)
    expect(mock.mock.calls.some(([url]) => url.endsWith('/payments/transfer'))).toBe(false)
    expect((screen.getByRole('button', { name: 'Confirm and send ₹12.30' }) as HTMLButtonElement).disabled).toBe(false)
  })
})
