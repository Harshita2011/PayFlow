import { createQrPayload } from './qrPayload'

async function loadQrReader() {
  try { return await import('@zxing/browser') }
  catch (cause) { throw new Error('The QR reader could not load. Check your connection and try again.', { cause }) }
}

export async function generateQrPng(upiId: string): Promise<string> {
  const { default: QRCode } = await import('qrcode')
  return QRCode.toDataURL(createQrPayload(upiId), {
    type: 'image/png', width: 360, margin: 4, errorCorrectionLevel: 'M',
    color: { dark: '#102419ff', light: '#ffffffff' },
  })
}

export function cameraErrorMessage(error: unknown): string {
  // DOMExceptions can originate in another browser realm and fail instanceof Error.
  const name = error && typeof error === 'object' && 'name' in error ? error.name : ''
  if (name === 'NotAllowedError' || name === 'SecurityError') return 'Camera permission was denied. Allow access in your browser or upload a QR image.'
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError') return 'No camera was found. Upload a QR image instead.'
  if (name === 'NotReadableError' || name === 'TrackStartError') return 'The camera is busy or unavailable. Close other camera apps or upload a QR image.'
  if (name === 'TimeoutError') return 'The camera preview could not start. Try another camera or upload a QR image.'
  return 'Camera scanning is unavailable. Use HTTPS or localhost, check your camera, or upload a QR image.'
}

export interface CameraSession { stop: () => void }

export function startCameraScan(
  video: HTMLVideoElement,
  onRead: (content: string) => void,
  onError: (message: string) => void,
  onReady: () => void,
): CameraSession {
  let stopped = false
  let stream: MediaStream | null = null
  let controls: CameraSession | null = null
  let startupTimer: ReturnType<typeof setTimeout> | undefined
  function stopTracks(value: MediaStream) {
    for (const track of value.getTracks()) {
      try { track.stop() } catch { /* Release remaining tracks even if one has already ended. */ }
    }
  }
  function stop() {
    if (stopped) return
    stopped = true
    clearTimeout(startupTimer)
    try { controls?.stop() } catch { /* Explicitly release our owned stream below. */ }
    if (stream) stopTracks(stream)
    video.srcObject = null
  }
  void (async () => {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('Unsupported camera')
    const { BrowserQRCodeReader } = await loadQrReader()
    if (stopped) return
    const acquired = await navigator.mediaDevices.getUserMedia({
      audio: false, video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 } },
    })
    if (stopped) { stopTracks(acquired); return }
    stream = acquired
    const reader = new BrowserQRCodeReader(undefined, { delayBetweenScanAttempts: 200 })
    const timeout = new Promise<never>((_resolve, reject) => {
      startupTimer = setTimeout(() => reject(new DOMException('Preview timed out', 'TimeoutError')), 10000)
    })
    const initializing = reader.decodeFromStream(acquired, video, (result, _error, activeControls) => {
      if (!result || stopped) return
      // Stop before interpreting any payload, including a malicious/unrelated QR.
      controls = activeControls
      stop()
      onRead(result.getText())
    }).then((activeControls) => {
      if (stopped) activeControls.stop()
      return activeControls
    })
    try { controls = await Promise.race([initializing, timeout]) }
    finally { clearTimeout(startupTimer) }
    if (stopped) controls.stop()
    else onReady()
  })().catch((error: unknown) => {
    if (stopped) return
    stop()
    onError(cameraErrorMessage(error))
  })
  return { stop }
}

export async function decodeQrImage(file: File, signal: AbortSignal): Promise<string> {
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size === 0 || file.size > 5 * 1024 * 1024) {
    throw new Error('Choose a PNG, JPG, or WebP image up to 5 MB.')
  }
  signal.throwIfAborted()
  const url = URL.createObjectURL(file)
  const image = new Image()
  let abort: () => void = () => {}
  try {
    await new Promise<void>((resolve, reject) => {
      abort = () => { image.src = ''; reject(new DOMException('Cancelled', 'AbortError')) }
      signal.addEventListener('abort', abort, { once: true })
      image.onload = () => resolve()
      image.onerror = () => reject(new Error('The image could not be opened. Try another PNG, JPG, or WebP.'))
      image.src = url
    })
    signal.throwIfAborted()
    if (image.naturalWidth > 4096 || image.naturalHeight > 4096 || !image.naturalWidth || !image.naturalHeight) {
      throw new Error('Use a clear QR image no larger than 4096 × 4096 pixels.')
    }
    const { BrowserQRCodeReader } = await loadQrReader()
    signal.throwIfAborted()
    try {
      const result = await new BrowserQRCodeReader().decodeFromImageElement(image)
      signal.throwIfAborted()
      return result.getText()
    } catch (error) {
      if (signal.aborted) throw error
      throw new Error('No readable QR code was found. Try a clear, cropped image with its white border.', { cause: error })
    }
  } finally {
    signal.removeEventListener('abort', abort)
    image.onload = null
    image.onerror = null
    image.src = ''
    URL.revokeObjectURL(url)
  }
}
