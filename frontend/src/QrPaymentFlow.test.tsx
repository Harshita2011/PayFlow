import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PaymentPanel from './PaymentPanel'
import { createQrPayload } from './qrPayload'

const media = vi.hoisted(() => ({ decode: vi.fn(), start: vi.fn(), stop: vi.fn(), png: vi.fn() }))
vi.mock('./qrMedia', () => ({ decodeQrImage: media.decode, startCameraScan: media.start, generateQrPng: media.png }))
const sender = { bank_name: 'Grove Demo Bank', masked_account_number: 'SIM •••• •••• •••• 1234', upi_id: 'sender@payflow', balance: '1000.00' }
const recipient = { display_name: 'Verified Recipient', bank_name: 'River Demo Bank', upi_id: 'recipient@payflow' }
const receipt = { transaction_id: 'qr-transfer-id', type: 'TRANSFER', direction: 'OUTGOING', status: 'SUCCESS', amount: '125.50', currency: 'INR', counterparty_name: recipient.display_name, counterparty_upi_id: recipient.upi_id, recipient_upi_id: recipient.upi_id, note: 'QR lunch', failure_reason: null, created_at: '2026-11-03T12:00:00Z' }
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })

beforeEach(() => {
  vi.clearAllMocks()
  media.decode.mockResolvedValue(createQrPayload(recipient.upi_id))
  media.start.mockReturnValue({ stop: media.stop })
})

function setup(handler?: (url: string, options?: RequestInit) => Promise<Response>) {
  const mock = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.includes('/history')) return json({ items: [], next_cursor: null })
    if (handler) return handler(url, options)
    if (url.endsWith('/resolve')) return json(recipient)
    return json(receipt, 201)
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

function panel(logout = vi.fn(), balance = vi.fn().mockResolvedValue(undefined)) {
  return render(<PaymentPanel token="test-token" accountId={3} senderAccount={sender} onLogout={logout} onBalanceChanged={balance} />)
}

function upload() {
  fireEvent.click(screen.getByRole('button', { name: 'Upload QR Image' }))
  fireEvent.change(screen.getByLabelText('Upload QR Image'), { target: { files: [new File(['png'], 'qr.png', { type: 'image/png' })] } })
}

async function reviewQr() {
  upload()
  await screen.findByText(`Verified recipient: ${recipient.display_name}`)
  fireEvent.change(screen.getByLabelText('Amount · INR'), { target: { value: '125.50' } })
  fireEvent.change(screen.getByLabelText('Note · optional'), { target: { value: 'QR lunch' } })
  fireEvent.submit(screen.getByRole('form', { name: 'Send simulated money' }))
  await screen.findByText('Confirm your simulated payment')
}

describe('QR to existing atomic payment flow', () => {
  it('verifies a QR recipient, requires amount/review/confirmation, then uses the existing transfer and receipt', async () => {
    const mock = setup()
    const balance = vi.fn().mockResolvedValue(undefined)
    panel(vi.fn(), balance)
    upload()
    await screen.findByText(`Verified recipient: ${recipient.display_name}`)
    expect((screen.getByLabelText('Recipient UPI ID') as HTMLInputElement).readOnly).toBe(true)
    expect((screen.getByLabelText('Amount · INR') as HTMLInputElement).value).toBe('')
    expect(mock.mock.calls.filter(([url]) => url.endsWith('/transfer'))).toHaveLength(0)
    fireEvent.change(screen.getByLabelText('Amount · INR'), { target: { value: '125.50' } })
    fireEvent.submit(screen.getByRole('form', { name: 'Send simulated money' }))
    await screen.findByText('Confirm your simulated payment')
    expect(screen.getByText(/From Grove Demo Bank/).textContent).toContain('1234')
    expect(mock.mock.calls.filter(([url]) => url.endsWith('/transfer'))).toHaveLength(0)
    fireEvent.click(screen.getByRole('button', { name: 'Confirm and send ₹125.50' }))
    await screen.findByText('Simulated payment completed.')
    expect(within(screen.getByRole('article', { name: 'Payment receipt' })).getByText(/qr-transfer-id/)).toBeTruthy()
    const sent = mock.mock.calls.find(([url]) => url.endsWith('/transfer'))!
    expect(JSON.parse(String(sent[1]?.body))).toEqual({ upi_id: recipient.upi_id, amount: '125.50', note: '', channel: 'QR' })
    expect(balance).toHaveBeenCalledOnce()
  })

  it('handles a QR-initiated insufficient-funds receipt without moving into a new payment automatically', async () => {
    const mock = setup(async (url) => url.endsWith('/resolve') ? json(recipient) : json({ detail: 'Insufficient simulated funds', receipt: { ...receipt, status: 'FAILED', failure_reason: 'Insufficient simulated funds' } }, 400))
    panel()
    await reviewQr()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm and send ₹125.50' }))
    await screen.findByText('Insufficient simulated funds')
    expect(screen.getByRole('article', { name: 'Payment receipt' }).textContent).toContain('No funds moved.')
    expect(mock.mock.calls.filter(([url]) => url.endsWith('/transfer'))).toHaveLength(1)
  })

  it('retains the same QR payment key and payload across an uncertain network outcome', async () => {
    let sends = 0
    const mock = setup(async (url) => {
      if (url.endsWith('/resolve')) return json(recipient)
      if (++sends === 1) throw new TypeError('Response lost')
      return json(receipt, 201)
    })
    panel()
    await reviewQr()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm and send ₹125.50' }))
    await screen.findByText('Keep this payment request.')
    expect((screen.getByRole('button', { name: 'Scan QR' }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Retry same request' }))
    await screen.findByText('Simulated payment completed.')
    const requests = mock.mock.calls.filter(([url]) => url.endsWith('/transfer'))
    expect(requests).toHaveLength(2)
    expect(requests[0][1]?.headers).toEqual(requests[1][1]?.headers)
    expect(requests[0][1]?.body).toBe(requests[1][1]?.body)
  })

  it('prevents duplicate QR confirmation submits', async () => {
    let resolve!: (value: Response) => void
    const mock = setup(async (url) => url.endsWith('/resolve') ? json(recipient) : new Promise((done) => { resolve = done }))
    panel()
    await reviewQr()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm and send ₹125.50' }))
    const sending = screen.getByRole('button', { name: 'Sending…' }) as HTMLButtonElement
    expect(sending.disabled).toBe(true)
    fireEvent.click(sending)
    expect(mock.mock.calls.filter(([url]) => url.endsWith('/transfer'))).toHaveLength(1)
    await act(async () => { resolve(json(receipt, 201)) })
    await screen.findByText('Simulated payment completed.')
  })

  it.each([['Recipient not available', 404], ['Could not reach PayFlow', 503]])('handles lookup failure: %s', async (detail, status) => {
    const mock = setup(async () => json({ detail }, status))
    panel()
    upload()
    expect((await screen.findByRole('alert')).textContent).toBe(detail)
    expect(mock.mock.calls.some(([url]) => url.endsWith('/transfer'))).toBe(false)
  })

  it('handles expired authentication while verifying a QR', async () => {
    setup(async () => json({ detail: 'Expired access token' }, 401))
    const logout = vi.fn()
    panel(logout)
    upload()
    await waitFor(() => expect(logout).toHaveBeenCalledWith('Your session has expired. Please sign in again.'))
  })

  it('does not fill a recipient after the scanner was closed during verification', async () => {
    let resolve!: (value: Response) => void
    const mock = setup(async () => new Promise((done) => { resolve = done }))
    panel()
    upload()
    await waitFor(() => expect(mock.mock.calls.some(([url]) => url.endsWith('/resolve'))).toBe(true))
    fireEvent.click(screen.getByRole('button', { name: 'Close QR scanner' }))
    await act(async () => { resolve(json(recipient)) })
    expect(screen.queryByText(`Verified recipient: ${recipient.display_name}`)).toBeNull()
    expect((screen.getByLabelText('Recipient UPI ID') as HTMLInputElement).value).toBe('')
  })

  it('releases the active scanner when the authenticated panel unmounts at logout', () => {
    setup()
    const view = panel()
    fireEvent.click(screen.getByRole('button', { name: 'Scan QR' }))
    fireEvent.click(screen.getByRole('button', { name: 'Start camera' }))
    view.unmount()
    expect(media.stop).toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})
