import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError } from './api'
import { getSecurityStatus, getSecurityEvents, setupPin, changePin } from './securityApi'
import type { SecurityStatus, SecurityEvent } from './securityApi'
import { formatMoney } from './formatMoney'

export default function SecurityPanel({ token, onLogout }: { token: string; onLogout: (message?: string) => void }) {
  const [status, setStatus] = useState<SecurityStatus | null>(null)
  const [events, setEvents] = useState<SecurityEvent[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const mounted = useRef(true)
  const posting = useRef(false)
  const [revision, setRevision] = useState(0)
  const [now, setNow] = useState(() => Date.now())
  function report(e: unknown) {
    if (e instanceof ApiError && e.status === 401) onLogout('Your session has expired. Please sign in again.')
    else setError(e instanceof Error ? e.message : 'Security settings could not be loaded.')
  }
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => {
    let active = true
    Promise.all([getSecurityStatus(token), getSecurityEvents(token)]).then(([s, page]) => {
      if (active) { setStatus(s); setEvents(page.items); setCursor(page.next_cursor); setNow(Date.now()) }
    }).catch((e: unknown) => { if (active) report(e) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
    // Logout callbacks do not change security data; token/revision controls this request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, revision])
  useEffect(() => {
    if (!status?.locked_until) return
    const delay = Date.parse(status.locked_until) - Date.now()
    if (delay <= 0) return
    const timer = setTimeout(() => setNow(Date.now()), Math.min(delay + 50, 2147483000))
    return () => clearTimeout(timer)
  }, [status?.locked_until])
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (posting.current || !status) return
    const form = event.currentTarget
    const values = new FormData(form)
    const pin = String(values.get('pin') || ''), confirmation = String(values.get('confirmation') || '')
    if (pin !== confirmation) { setError('Payment PINs do not match.'); form.reset(); return }
    const password = String(values.get('password') || ''), current = String(values.get('current_pin') || '')
    form.reset() // Clear all sensitive input immediately, including on errors.
    posting.current = true; setBusy(true); setError(''); setMessage('')
    try {
      const result = status.pin_configured ? await changePin(token, current, pin) : await setupPin(token, pin, password)
      if (mounted.current) { setMessage(result.message); setRevision((value) => value + 1) }
    } catch (e) { if (mounted.current) report(e) }
    finally { posting.current = false; if (mounted.current) setBusy(false) }
  }
  const locked = !!(status?.locked_until && Date.parse(status.locked_until) > now)
  return <section className="surface security-panel" aria-label="Security Settings">
    <div className="account-heading"><h2>Security Settings</h2><button className="text-button" disabled={busy || loading} onClick={() => { setError(''); setLoading(true); setRevision((value) => value + 1) }}>Refresh security</button></div>
    <p className="account-note">Controls for simulated payments. These controls are not financial certification or a guarantee against fraud.</p>
    {loading && <p role="status">Loading security settings…</p>}{error && <p className="feedback error" role="alert">{error}</p>}{message && <p className="feedback success" role="status">{message}</p>}
    {status && <>
      {locked && <p className="feedback error" role="alert">Payment PIN temporarily locked until {new Date(status.locked_until!).toLocaleString()}. Wait, then refresh security to try again.</p>}
      <h3>{status.pin_configured ? 'Change Payment PIN' : 'Set Payment PIN'}</h3>
      <p>Use six digits, avoiding repeated digits and obvious sequences. {status.pin_configured ? 'Changing it requires your current PIN and invalidates earlier unconsumed authorizations.' : 'Initial setup requires your account password. No default PIN is assigned.'}</p>
      <form aria-label={status.pin_configured ? 'Change Payment PIN' : 'Set Payment PIN'} onSubmit={submit}><fieldset disabled={busy || locked}>
        {status.pin_configured ? <label>Current payment PIN<input name="current_pin" type="password" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} minLength={6} autoComplete="off" required /></label> : <label>Account password<input name="password" type="password" maxLength={128} autoComplete="current-password" required /></label>}
        <label>New payment PIN<input name="pin" type="password" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} minLength={6} autoComplete="off" required /></label>
        <label>Confirm payment PIN<input name="confirmation" type="password" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} minLength={6} autoComplete="off" required /></label>
        <button className="primary-button">{busy ? 'Saving…' : status.pin_configured ? 'Change PIN' : 'Set PIN'}</button>
      </fieldset></form>
      <p className="account-note">Forgotten PIN reset is unavailable until an independent recovery mechanism exists. An active login alone cannot reset a configured PIN.</p>
      <h3>Payment limits</h3><p>Single payment: {formatMoney(status.single_limit)}. Daily outgoing amount: {formatMoney(status.daily_limit)}; used {formatMoney(status.daily_amount_used)}. Daily count: {status.daily_count_used} / {status.daily_count_limit}.</p><p className="account-note">Resets at 00:00 UTC. Self-transfers count; controlled demo funding does not.</p>
      <h3>Your security activity</h3>{events.length === 0 && <p>No recent security activity.</p>}<ul className="security-events">{events.map((item) => <li key={item.id}><strong>{item.event_type.replaceAll('_', ' ')}</strong> · {item.outcome}<br /><span>{new Date(item.created_at).toLocaleString()}</span>{item.details.rules?.length ? <p className="feedback error">Demo risk rule: {item.details.rules.join(', ')}</p> : null}</li>)}</ul>
      {cursor && <button className="secondary-button" disabled={busy} onClick={async () => { setBusy(true); try { const page = await getSecurityEvents(token, cursor); if (mounted.current) { setEvents((items) => [...items, ...page.items]); setCursor(page.next_cursor) } } catch (e) { if (mounted.current) report(e) } finally { if (mounted.current) setBusy(false) } }}>Older security events</button>}
    </>}
  </section>
}
