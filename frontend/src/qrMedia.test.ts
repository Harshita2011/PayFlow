import { describe, expect, it, vi } from 'vitest'
import { waitFor } from '@testing-library/react'
import { decodeQrImage, generateQrPng, startCameraScan } from './qrMedia'

const mock = vi.hoisted(() => ({ stream: vi.fn(), image: vi.fn(), png: vi.fn() }))
vi.mock('@zxing/browser', () => ({ BrowserQRCodeReader: class {
  decodeFromStream = mock.stream
  decodeFromImageElement = mock.image
} }))
vi.mock('qrcode', () => ({ default: { toDataURL: mock.png } }))

function camera(getUserMedia: ReturnType<typeof vi.fn>) {
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } })
}

describe('QR encoding and media lifecycle', () => {
  it('generates a high-contrast PNG with a four-module quiet zone and no private fields', async () => {
    mock.png.mockResolvedValue('data:image/png;base64,test')
    expect(await generateQrPng('alex@payflow')).toBe('data:image/png;base64,test')
    expect(mock.png).toHaveBeenCalledWith('payflow://pay?v=1&upi=alex%40payflow', expect.objectContaining({ margin: 4, type: 'image/png', errorCorrectionLevel: 'M' }))
  })

  it.each([
    ['NotAllowedError', /permission was denied/], ['NotFoundError', /No camera/],
    ['NotReadableError', /busy or unavailable/],
  ])('handles %s without leaving a camera session running', async (name, message) => {
    camera(vi.fn().mockRejectedValue(new DOMException('Camera error', name)))
    const onError = vi.fn()
    startCameraScan(document.createElement('video'), vi.fn(), onError, vi.fn())
    await waitFor(() => expect(onError).toHaveBeenCalledWith(expect.stringMatching(message)))
  })

  it('handles unsupported browsers and secure-context restrictions', async () => {
    vi.stubGlobal('navigator', {})
    const onError = vi.fn()
    startCameraScan(document.createElement('video'), vi.fn(), onError, vi.fn())
    await waitFor(() => expect(onError).toHaveBeenCalledWith(expect.stringMatching(/HTTPS or localhost/)))
  })

  it('stops decoding and every track before delivering a scan, and ignores duplicate frames', async () => {
    const track = { stop: vi.fn() }
    const stream = { getTracks: () => [track] }
    const controls = { stop: vi.fn() }
    mock.stream.mockResolvedValue(controls)
    camera(vi.fn().mockResolvedValue(stream))
    const onRead = vi.fn()
    const ready = vi.fn()
    const video = document.createElement('video')
    const session = startCameraScan(video, onRead, vi.fn(), ready)
    await waitFor(() => expect(ready).toHaveBeenCalled())
    const callback = mock.stream.mock.calls.at(-1)![2]
    callback({ getText: () => 'decoded' }, undefined, controls)
    callback({ getText: () => 'duplicate' }, undefined, controls)
    expect(track.stop).toHaveBeenCalled()
    expect(controls.stop).toHaveBeenCalled()
    expect(onRead).toHaveBeenCalledExactlyOnceWith('decoded')
    expect(video.srcObject).toBeNull()
    session.stop()
  })

  it('releases a stream granted after closing during a pending permission prompt', async () => {
    let grant!: (stream: unknown) => void
    const getUserMedia = vi.fn().mockImplementation(() => new Promise((resolve) => { grant = resolve }))
    camera(getUserMedia)
    const track = { stop: vi.fn() }
    const ready = vi.fn()
    const session = startCameraScan(document.createElement('video'), vi.fn(), vi.fn(), ready)
    await waitFor(() => expect(getUserMedia).toHaveBeenCalled())
    session.stop()
    grant({ getTracks: () => [track] })
    await waitFor(() => expect(track.stop).toHaveBeenCalled())
    expect(ready).not.toHaveBeenCalled()
  })

  it('does not request camera permission if cancelled while the decoder is loading', async () => {
    const getUserMedia = vi.fn()
    camera(getUserMedia)
    startCameraScan(document.createElement('video'), vi.fn(), vi.fn(), vi.fn()).stop()
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(getUserMedia).not.toHaveBeenCalled()
  })

  it('cleans up an acquired stream when decoder initialization fails', async () => {
    const track = { stop: vi.fn() }
    camera(vi.fn().mockResolvedValue({ getTracks: () => [track] }))
    mock.stream.mockRejectedValueOnce(new Error('Decoder failed'))
    const onError = vi.fn()
    startCameraScan(document.createElement('video'), vi.fn(), onError, vi.fn())
    await waitFor(() => expect(onError).toHaveBeenCalled())
    expect(track.stop).toHaveBeenCalled()
  })

  it('bounds stalled preview startup and stops a decoder that finishes after timeout', async () => {
    vi.useFakeTimers()
    const track = { stop: vi.fn() }
    camera(vi.fn().mockResolvedValue({ getTracks: () => [track] }))
    let finish!: (controls: { stop: () => void }) => void
    mock.stream.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    const onError = vi.fn()
    startCameraScan(document.createElement('video'), vi.fn(), onError, vi.fn())
    await vi.advanceTimersByTimeAsync(10001)
    expect(onError).toHaveBeenCalledWith(expect.stringMatching(/preview could not start/))
    expect(track.stop).toHaveBeenCalled()
    const stop = vi.fn()
    finish({ stop })
    await vi.advanceTimersByTimeAsync(0)
    expect(stop).toHaveBeenCalled()
  })

  it('rejects unsupported image types, empty files, and oversize files', async () => {
    for (const file of [new File(['svg'], 'a.svg', { type: 'image/svg+xml' }), new File([], 'empty.png', { type: 'image/png' }), new File([new Uint8Array(5 * 1024 * 1024 + 1)], 'large.png', { type: 'image/png' })]) {
      await expect(decodeQrImage(file, new AbortController().signal)).rejects.toThrow(/PNG, JPG, or WebP/)
    }
  })

  function imageEnvironment(width = 360, broken = false) {
    const revoke = vi.fn()
    vi.stubGlobal('URL', { createObjectURL: vi.fn().mockReturnValue('blob:local-test'), revokeObjectURL: revoke })
    vi.stubGlobal('Image', class {
      naturalWidth = width
      naturalHeight = 360
      onload: ((event: Event) => void) | null = null
      onerror: ((event: Event) => void) | null = null
      set src(value: string) { if (value) queueMicrotask(() => broken ? this.onerror?.(new Event('error')) : this.onload?.(new Event('load'))) }
    })
    return revoke
  }

  it('decodes images locally and revokes the object URL after success', async () => {
    const revoke = imageEnvironment()
    mock.image.mockResolvedValueOnce({ getText: () => 'payflow://pay?v=1&upi=alex%40payflow' })
    expect(await decodeQrImage(new File(['png'], 'qr.png', { type: 'image/png' }), new AbortController().signal)).toContain('payflow://')
    expect(revoke).toHaveBeenCalledWith('blob:local-test')
  })

  it('reports unreadable/corrupt images and still revokes their URLs', async () => {
    const revoke = imageEnvironment()
    mock.image.mockRejectedValueOnce(new Error('Not found'))
    await expect(decodeQrImage(new File(['png'], 'qr.png', { type: 'image/png' }), new AbortController().signal)).rejects.toThrow(/No readable QR/)
    expect(revoke).toHaveBeenCalled()
    imageEnvironment(360, true)
    await expect(decodeQrImage(new File(['bad'], 'bad.png', { type: 'image/png' }), new AbortController().signal)).rejects.toThrow(/could not be opened/)
  })

  it('rejects excessive image dimensions before invoking the decoder', async () => {
    const revoke = imageEnvironment(5000)
    const count = mock.image.mock.calls.length
    await expect(decodeQrImage(new File(['png'], 'qr.png', { type: 'image/png' }), new AbortController().signal)).rejects.toThrow(/4096/)
    expect(mock.image.mock.calls.length).toBe(count)
    expect(revoke).toHaveBeenCalled()
  })

  it('revokes an image URL when upload decoding is cancelled', async () => {
    const revoke = imageEnvironment()
    const controller = new AbortController()
    const pending = decodeQrImage(new File(['png'], 'qr.png', { type: 'image/png' }), controller.signal)
    controller.abort()
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
    expect(revoke).toHaveBeenCalledWith('blob:local-test')
  })
})
