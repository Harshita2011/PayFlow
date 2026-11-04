import { useEffect, useState } from 'react'
import { generateQrPng } from './qrMedia'

export default function MyQrCode({ upiId, initiallyOpen = false }: { upiId: string; initiallyOpen?: boolean }) {
  const [open, setOpen] = useState(initiallyOpen)
  const [image, setImage] = useState('')
  const [generatedFor, setGeneratedFor] = useState('')
  const [loading, setLoading] = useState(initiallyOpen)
  const [error, setError] = useState('')
  const [copiedFor, setCopiedFor] = useState('')
  const currentImage = generatedFor === upiId ? image : ''

  useEffect(() => {
    if (!open) return
    let active = true
    generateQrPng(upiId).then((url) => { if (active) { setImage(url); setGeneratedFor(upiId); setError('') } })
      .catch(() => { if (active) setError('Your QR could not be generated. Close and reopen it to try again.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [open, upiId])

  async function copyUpi() {
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable')
      await navigator.clipboard.writeText(upiId)
      setCopiedFor(upiId)
      setError('')
    } catch { setError('Copy is unavailable. Select and copy the UPI ID shown below the QR.') }
  }

  return <section className="my-qr" aria-labelledby="my-qr-title">
    <div className="account-heading"><h4 id="my-qr-title">My QR Code</h4><button className="text-button" aria-expanded={open} aria-controls="my-qr-content" onClick={() => {
      if (!open) { setImage(''); setLoading(true); setError(''); setCopiedFor('') }
      setOpen(!open)
    }}>{open ? 'Hide my QR' : 'Show my QR'}</button></div>
    {open && <div id="my-qr-content" className="my-qr-content">
      {(loading || (!currentImage && !error)) && <p role="status" className="account-note">Generating your PayFlow QR…</p>}
      {currentImage && <img className="my-qr-image" src={currentImage} width={260} height={260} alt="Your PayFlow sandbox payment QR code" />}
      <p className="qr-upi">{upiId}</p>
      <p className="account-note">Public sandbox identity only. Not an official UPI payment request.</p>
      {error && <p role="alert" className="feedback error">{error}</p>}
      {copiedFor === upiId && <p role="status" className="account-note">UPI ID copied.</p>}
      <div className="qr-actions"><button className="secondary-button" onClick={copyUpi}>Copy UPI ID</button>{currentImage && <a className="secondary-button qr-download" href={currentImage} download="payflow-qr.png">Download QR as PNG</a>}</div>
    </div>}
  </section>
}
