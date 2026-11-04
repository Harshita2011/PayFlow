import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import { decodeQrImage, startCameraScan } from './qrMedia'
import type { CameraSession } from './qrMedia'
import { parseQrPayload } from './qrPayload'

interface Props {
  ownUpiId: string
  onRecipient: (upiId: string, signal: AbortSignal) => Promise<void>
  onClose: () => void
}

export default function QrScanner({ ownUpiId, onRecipient, onClose }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)
  const video = useRef<HTMLVideoElement>(null)
  const camera = useRef<CameraSession | null>(null)
  const imageRequest = useRef<AbortController | null>(null)
  const verificationRequest = useRef<AbortController | null>(null)
  const generation = useRef(0)
  const [cameraState, setCameraState] = useState<'off' | 'starting' | 'scanning'>('off')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const element = dialog.current!
    const previous = document.activeElement as HTMLElement | null
    element.showModal()
    return () => {
      generation.current += 1
      camera.current?.stop()
      imageRequest.current?.abort()
      verificationRequest.current?.abort()
      element.close()
      if (previous?.isConnected) previous.focus()
    }
  }, [])

  async function accept(content: string, current: number) {
    if (current !== generation.current) return
    camera.current?.stop()
    setCameraState('off')
    setBusy(true)
    setError('')
    try {
      const upiId = parseQrPayload(content, ownUpiId)
      const request = new AbortController()
      verificationRequest.current = request
      await onRecipient(upiId, request.signal)
      if (current === generation.current) onClose()
    } catch (failure) {
      if (current === generation.current) setError(failure instanceof Error ? failure.message : 'Could not verify this QR recipient.')
    } finally { if (current === generation.current) setBusy(false) }
  }

  function startCamera() {
    if (!video.current || busy) return
    imageRequest.current?.abort()
    camera.current?.stop()
    const current = ++generation.current
    setError('')
    setCameraState('starting')
    camera.current = startCameraScan(video.current,
      (content) => { void accept(content, current) },
      (message) => { if (current === generation.current) { setError(message); setCameraState('off') } },
      () => { if (current === generation.current) setCameraState('scanning') },
    )
  }

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || busy) return
    camera.current?.stop()
    setCameraState('off')
    imageRequest.current?.abort()
    const request = new AbortController()
    imageRequest.current = request
    const current = ++generation.current
    setBusy(true)
    setError('')
    try { await accept(await decodeQrImage(file, request.signal), current) }
    catch (failure) {
      if (current === generation.current) setError(failure instanceof Error ? failure.message : 'This image could not be scanned.')
    } finally { if (current === generation.current) setBusy(false) }
  }

  return <dialog ref={dialog} className="qr-dialog" aria-labelledby="scanner-title" aria-describedby="scanner-description" onCancel={(event) => { event.preventDefault(); onClose() }} onKeyDown={(event) => {
    if (event.key !== 'Tab' || event.ctrlKey || event.metaKey || event.altKey) return
    // Keep keyboard focus within the modal even when starting disables the focused button.
    const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), a[href], [tabindex="0"]'))
    if (!controls.length) return
    const index = controls.indexOf(document.activeElement as HTMLElement)
    const next = event.shiftKey ? (index <= 0 ? controls.length - 1 : index - 1) : (index < 0 || index === controls.length - 1 ? 0 : index + 1)
    event.preventDefault()
    controls[next].focus()
  }}>
    <div className="account-heading"><h3 id="scanner-title">Scan a PayFlow QR</h3><button className="text-button" onClick={onClose} aria-label="Close QR scanner">Close ✕</button></div>
    <p id="scanner-description" className="account-note">Scan with your camera or choose a saved image. We verify the recipient first. Scanning never sends money.</p>
    <div className="scanner-preview"><video ref={video} muted playsInline autoPlay aria-label="QR camera preview" /><span className="scanner-guide" aria-hidden="true" /></div>
    {cameraState === 'starting' && <p role="status" className="account-note">Waiting for camera permission… You can close this scanner at any time.</p>}
    {cameraState === 'scanning' && <p role="status" className="account-note">Point the camera at a clear PayFlow QR.</p>}
    {busy && <p role="status" className="account-note">Reading QR and verifying recipient…</p>}
    {error && <p role="alert" className="feedback error">{error}</p>}
    <div className="qr-actions"><button className="secondary-button" disabled={busy || cameraState !== 'off'} onClick={startCamera}>Start camera</button>{cameraState !== 'off' && <button className="secondary-button" onClick={() => { generation.current += 1; camera.current?.stop(); setCameraState('off') }}>Stop camera</button>}</div>
    <label className="qr-upload">Upload QR Image<input type="file" accept="image/png,image/jpeg,image/webp" disabled={busy} onChange={upload} /></label>
    <p className="account-note">PNG, JPG or WebP · up to 5 MB and 4096 × 4096 pixels. Images are decoded locally and are never uploaded to PayFlow’s server.</p>
  </dialog>
}
