import { useEffect, useState } from 'react'
import ConfirmDialog from './ConfirmDialog'

export default function PaymentPinDialog({ busy, error, retryUntil, onSubmit, onClose, onSettings }: { busy: boolean; error: string; retryUntil?: number | null; onSubmit: (pin: string) => Promise<void>; onClose: () => void; onSettings?: () => void }) {
  const [pin, setPin] = useState('')
  const [formatError, setFormatError] = useState('')
  const [now, setNow] = useState(() => Date.now())
  const blocked = !!retryUntil && retryUntil > now
  useEffect(() => {
    if (!retryUntil) return
    const timer = setTimeout(() => setNow(Date.now()), Math.min(Math.max(0, retryUntil-Date.now())+50, 2147483000))
    return () => clearTimeout(timer)
  }, [retryUntil])
  async function submit() {
    if (busy || blocked) return
    if (!/^[0-9]{6}$/.test(pin)) { setFormatError('Enter your six-digit payment PIN.'); return }
    const value = pin
    setPin(''); setFormatError('')
    await onSubmit(value)
  }
  return <ConfirmDialog title="Authorize simulated payment" action="Verify PIN and pay" busy={busy} actionDisabled={blocked} onConfirm={submit} onClose={onClose}>
    <p>This PIN authorizes only the reviewed payment. It is separate from your account password.</p>
    <form aria-label="Payment PIN authorization" onSubmit={(event) => { event.preventDefault(); void submit() }}><label>Payment PIN<input type="password" inputMode="numeric" autoComplete="off" pattern="[0-9]{6}" minLength={6} maxLength={6} value={pin} disabled={busy || blocked} onChange={(event) => setPin(event.target.value)} /></label></form>
    {(error || formatError) && <p className="feedback error" role="alert">{error || formatError}</p>}
    {blocked && <p className="account-note">Try again after {new Date(retryUntil!).toLocaleTimeString()}.</p>}
    <p className="account-note">A temporary lockout follows repeated incorrect attempts. Forgotten PIN recovery is not available: a login token alone cannot reset it.</p>
    {onSettings && <button className="text-button" disabled={busy} onClick={onSettings}>Open Security Settings</button>}
  </ConfirmDialog>
}
