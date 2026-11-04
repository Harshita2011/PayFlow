import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import QrScanner from './QrScanner'
import MyQrCode from './MyQrCode'
import { createQrPayload } from './qrPayload'

const mock = vi.hoisted(() => ({ start: vi.fn(), stop: vi.fn(), decode: vi.fn(), png: vi.fn() }))
vi.mock('./qrMedia', () => ({ startCameraScan: mock.start, decodeQrImage: mock.decode, generateQrPng: mock.png }))

beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(HTMLDialogElement.prototype, 'showModal').mockImplementation(function (this: HTMLDialogElement) { this.setAttribute('open', '') })
  vi.spyOn(HTMLDialogElement.prototype, 'close').mockImplementation(function (this: HTMLDialogElement) { this.removeAttribute('open') })
  mock.start.mockImplementation(() => ({ stop: mock.stop }))
  mock.png.mockResolvedValue('data:image/png;base64,test')
})

function upload() {
  fireEvent.change(screen.getByLabelText('Upload QR Image'), { target: { files: [new File(['png'], 'qr.png', { type: 'image/png' })] } })
}

describe('QR scanner and my QR', () => {
  it('hides the old QR and download while a different account identity is being encoded', async () => {
    let resolve!: (image: string) => void
    mock.png.mockResolvedValueOnce('data:image/png;base64,old').mockImplementationOnce(() => new Promise((done) => { resolve = done }))
    const view = render(<MyQrCode upiId="first@payflow" initiallyOpen />)
    await screen.findByRole('img')
    view.rerender(<MyQrCode upiId="second@payflow" initiallyOpen />)
    expect(screen.queryByRole('img')).toBeNull()
    expect(screen.queryByRole('link', { name: 'Download QR as PNG' })).toBeNull()
    expect(screen.getByText('second@payflow')).toBeTruthy()
    await act(async () => { resolve('data:image/png;base64,new') })
    expect((await screen.findByRole('img')).getAttribute('src')).toBe('data:image/png;base64,new')
  })
  it('wraps Tab and Shift+Tab within the dialog', () => {
    render(<QrScanner ownUpiId="self@payflow" onRecipient={vi.fn()} onClose={vi.fn()} />)
    const close = screen.getByRole('button', { name: 'Close QR scanner' })
    const file = screen.getByLabelText('Upload QR Image')
    close.focus()
    fireEvent.keyDown(close, { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(file)
    fireEvent.keyDown(file, { key: 'Tab' })
    expect(document.activeElement).toBe(close)
  })
  it('never starts the camera before an explicit Start camera click, and releases it on close/unmount', () => {
    const close = vi.fn()
    const view = render(<QrScanner ownUpiId="self@payflow" onRecipient={vi.fn()} onClose={close} />)
    expect(mock.start).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Start camera' }))
    expect(mock.start).toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Close QR scanner' }))
    expect(close).toHaveBeenCalled()
    view.unmount()
    expect(mock.stop).toHaveBeenCalled()
  })

  it('provides camera error feedback and keeps image upload available', () => {
    mock.start.mockImplementation((_video, _read, onError) => { onError('Camera permission was denied. Upload an image.'); return { stop: mock.stop } })
    render(<QrScanner ownUpiId="self@payflow" onRecipient={vi.fn()} onClose={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Start camera' }))
    expect(screen.getByRole('alert').textContent).toContain('permission was denied')
    expect((screen.getByLabelText('Upload QR Image') as HTMLInputElement).disabled).toBe(false)
  })

  it('decodes an upload, validates it, and passes only the public ID for backend verification', async () => {
    mock.decode.mockResolvedValueOnce(createQrPayload('alex@payflow'))
    const recipient = vi.fn().mockResolvedValue(undefined)
    const close = vi.fn()
    render(<QrScanner ownUpiId="self@payflow" onRecipient={recipient} onClose={close} />)
    upload()
    await waitFor(() => expect(recipient).toHaveBeenCalledWith('alex@payflow', expect.any(AbortSignal)))
    expect(close).toHaveBeenCalled()
    expect(mock.start).not.toHaveBeenCalled()
  })

  it.each(['https://attacker.example', createQrPayload('self@payflow'), 'payflow://pay?v=2&upi=alex%40payflow'])('rejects untrusted or self content without lookup: %s', async (content) => {
    mock.decode.mockResolvedValueOnce(content)
    const recipient = vi.fn()
    const location = window.location.href
    render(<QrScanner ownUpiId="self@payflow" onRecipient={recipient} onClose={vi.fn()} />)
    upload()
    await screen.findByRole('alert')
    expect(recipient).not.toHaveBeenCalled()
    expect(window.location.href).toBe(location)
  })

  it('shows unknown-recipient errors instead of closing or sending anything', async () => {
    mock.decode.mockResolvedValueOnce(createQrPayload('missing@payflow'))
    const close = vi.fn()
    render(<QrScanner ownUpiId="self@payflow" onRecipient={vi.fn().mockRejectedValue(new Error('Recipient not available'))} onClose={close} />)
    upload()
    expect((await screen.findByRole('alert')).textContent).toBe('Recipient not available')
    expect(close).not.toHaveBeenCalled()
  })

  it('supports Escape/cancel and aborts decoding when logging out/unmounting', async () => {
    let resolve!: (value: string) => void
    mock.decode.mockImplementationOnce(() => new Promise<string>((done) => { resolve = done }))
    const recipient = vi.fn()
    const close = vi.fn()
    const view = render(<QrScanner ownUpiId="self@payflow" onRecipient={recipient} onClose={close} />)
    upload()
    const signal = mock.decode.mock.calls.at(-1)![1] as AbortSignal
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { cancelable: true }))
    expect(close).toHaveBeenCalled()
    view.unmount()
    expect(signal.aborted).toBe(true)
    await act(async () => { resolve(createQrPayload('alex@payflow')) })
    expect(recipient).not.toHaveBeenCalled()
  })

  it('generates only on request, shows the ID, supports copy and PNG download', async () => {
    const copy = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText: copy } })
    render(<MyQrCode upiId="alex@payflow" />)
    const count = mock.png.mock.calls.length
    expect(screen.queryByRole('img')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Show my QR' }))
    await screen.findByRole('img', { name: 'Your PayFlow sandbox payment QR code' })
    expect(mock.png.mock.calls.length).toBe(count + 1)
    expect(screen.getByText('alex@payflow')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Download QR as PNG' }).getAttribute('download')).toBe('payflow-qr.png')
    fireEvent.click(screen.getByRole('button', { name: 'Copy UPI ID' }))
    await screen.findByText('UPI ID copied.')
    expect(copy).toHaveBeenCalledExactlyOnceWith('alex@payflow')
  })

  it('shows generation and clipboard failures with readable fallback text', async () => {
    mock.png.mockRejectedValueOnce(new Error('Canvas failed'))
    vi.stubGlobal('navigator', {})
    render(<MyQrCode upiId="alex@payflow" />)
    fireEvent.click(screen.getByRole('button', { name: 'Show my QR' }))
    await screen.findByRole('alert')
    fireEvent.click(screen.getByRole('button', { name: 'Copy UPI ID' }))
    await screen.findByText(/Select and copy the UPI ID/)
  })
})
