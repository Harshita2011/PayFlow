import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, fundDemo, getPaymentHistory, getPaymentReceipt, resolveRecipient, transferMoney } from './api'
import type { PaymentReceipt, Recipient, TransferInput } from './api'

interface Props {
  token: string
  accountId: number
  onLogout: (message?: string) => void
  onBalanceChanged: () => Promise<void>
}

type Intent = { key: string; kind: 'fund' | 'transfer'; payload?: TransferInput; uncertain: boolean }

const pendingKey = (accountId: number) => `payflow.pending.${accountId}`

function clearPending(accountId: number, key: string) {
  try {
    const stored = JSON.parse(sessionStorage.getItem(pendingKey(accountId)) || 'null')
    // A late response from a logged-out component must not erase a newer intent.
    if (stored?.key === key) sessionStorage.removeItem(pendingKey(accountId))
  } catch { /* Replaying a stale saved key is harmless; never turn a success into a retry error. */ }
}

function restoredIntent(accountId: number): Intent | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(pendingKey(accountId)) || 'null') as Intent | null
    if (!value || typeof value.key !== 'string' || !/^[0-9a-f-]{36}$/.test(value.key)) return null
    if (value.kind === 'fund') return { key: value.key, kind: 'fund', uncertain: true }
    if (value.kind === 'transfer' && value.payload && typeof value.payload.upi_id === 'string' &&
        typeof value.payload.amount === 'string' && typeof value.payload.note === 'string') {
      canonicalAmount(value.payload.amount)
      return { key: value.key, kind: 'transfer', payload: value.payload, uncertain: true }
    }
  } catch { /* Corrupt/unavailable browser storage is never trusted as an API authority. */ }
  return null
}

function canonicalAmount(value: string): string {
  if (!/^[0-9]{1,16}(\.[0-9]{1,2})?$/.test(value)) throw new Error('Enter an amount with at most two decimal places.')
  const [whole, fraction = ''] = value.split('.')
  const cents = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'))
  if (cents <= 0n || cents > 10000000n) throw new Error('Send between ₹0.01 and ₹100,000.00 in simulated funds.')
  return `${BigInt(whole)}.${fraction.padEnd(2, '0')}`
}

export default function PaymentPanel({ token, accountId, onLogout, onBalanceChanged }: Props) {
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [recipient, setRecipient] = useState<Recipient | null>(null)
  const [draft, setDraft] = useState<TransferInput | null>(null)
  const [intent, setIntent] = useState<Intent | null>(() => restoredIntent(accountId))
  const [receipt, setReceipt] = useState<PaymentReceipt | null>(null)
  const [items, setItems] = useState<PaymentReceipt[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState('')
  const [reload, setReload] = useState(0)
  const mounted = useRef(true)
  const posting = useRef(false)

  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])

  useEffect(() => {
    let active = true
    getPaymentHistory(token).then((data) => {
      if (!active) return
      setItems(data.items)
      setCursor(data.next_cursor)
    }).catch((error: unknown) => {
      if (!active) return
      if (error instanceof ApiError && error.status === 401) onLogout('Your session has expired. Please sign in again.')
      else setHistoryError(error instanceof Error ? error.message : 'Could not load history.')
    }).finally(() => { if (active) setHistoryLoading(false) })
    return () => { active = false }
  }, [token, onLogout, reload])

  function refreshHistory() {
    setHistoryLoading(true)
    setHistoryError('')
    setReload((value) => value + 1)
  }

  function handleError(error: unknown) {
    if (error instanceof ApiError && error.status === 401) onLogout('Your session has expired. Please sign in again.')
    else setFeedback(error instanceof Error ? error.message : 'Something went wrong. Please try again.')
  }

  async function review(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || intent) return
    const fields = new FormData(event.currentTarget)
    setFeedback('')
    try {
      const payload = {
        upi_id: String(fields.get('upi_id') || '').trim().toLowerCase(),
        amount: canonicalAmount(String(fields.get('amount') || '').trim()),
        note: String(fields.get('note') || '').trim(),
      }
      setBusy(true)
      const found = await resolveRecipient(token, payload.upi_id)
      if (!mounted.current) return
      setDraft(payload)
      setRecipient(found)
    } catch (error) {
      if (mounted.current) handleError(error)
    } finally { if (mounted.current) setBusy(false) }
  }

  async function pay(next: Intent) {
    if (posting.current) return
    posting.current = true
    try {
      // Persist BEFORE sending. Only the scoped retry key/payload, never the JWT.
      sessionStorage.setItem(pendingKey(accountId), JSON.stringify(next))
    } catch {
      posting.current = false
      setFeedback('Cannot save the retry key in this tab. Enable browser session storage before sending.')
      return
    }
    setBusy(true)
    setFeedback('')
    setIntent(next)
    let result: PaymentReceipt
    try {
      result = next.kind === 'fund' ? await fundDemo(token, next.key) : await transferMoney(token, next.key, next.payload!)
    } catch (error) {
      if (mounted.current) {
        if (error instanceof ApiError && error.status >= 400 && error.status < 500 && error.status !== 408) {
          clearPending(accountId, next.key)
          setIntent(null)
          setRecipient(null)
          const body = error.responseBody as { receipt?: PaymentReceipt } | undefined
          if (body?.receipt) setReceipt(body.receipt)
          handleError(error)
          refreshHistory()
        } else {
          setIntent({ ...next, uncertain: true })
          setFeedback('Outcome unknown. Retry this exact request with the same key. This tab saves the request for your account; check history before starting a different payment.')
        }
        setBusy(false)
      }
      posting.current = false
      return
    }
    clearPending(accountId, next.key)
    if (mounted.current) {
      setReceipt(result)
      setIntent(null)
      setRecipient(null)
      setDraft(null)
      setFeedback(next.kind === 'fund' ? 'Simulated funds added successfully.' : 'Simulated payment completed.')
      refreshHistory()
      try { await onBalanceChanged() }
      catch { if (mounted.current) setFeedback('Payment succeeded. Balance refresh failed; use Refresh accounts to check it.') }
      if (mounted.current) setBusy(false)
    }
    posting.current = false
  }

  async function moreHistory() {
    if (!cursor || historyLoading) return
    setHistoryLoading(true)
    setHistoryError('')
    try {
      const data = await getPaymentHistory(token, cursor)
      if (!mounted.current) return
      setItems((previous) => [...previous, ...data.items.filter((item) => !previous.some((old) => old.transaction_id === item.transaction_id))])
      setCursor(data.next_cursor)
    } catch (error) { if (mounted.current) handleError(error) }
    finally { if (mounted.current) setHistoryLoading(false) }
  }

  async function viewReceipt(id: string) {
    setBusy(true)
    try {
      const data = await getPaymentReceipt(token, id)
      if (mounted.current) setReceipt(data)
    } catch (error) { if (mounted.current) handleError(error) }
    finally { if (mounted.current) setBusy(false) }
  }

  return <section className="payment-panel" aria-labelledby="payments-title">
    <div className="account-heading"><h3 id="payments-title">Your payment sandbox</h3><span className="demo-tag">SIMULATED INR</span></div>
    <div className="demo-funding"><p>Add fictional test funds.<span>₹1,000 per action · 3 actions per user.</span></p><button className="secondary-button" disabled={busy || intent !== null} onClick={() => pay({ key: crypto.randomUUID(), kind: 'fund', uncertain: false })}>Add ₹1,000 demo funds</button></div>
    {feedback && <p className="feedback notice" role="status">{feedback}</p>}
    {intent?.uncertain && <div className="uncertain-payment" role="alert"><strong>Keep this payment request.</strong><p>{intent.kind === 'fund' ? 'Demo funding · ₹1,000.00' : `₹${intent.payload?.amount} to ${intent.payload?.upi_id}`}</p><button className="primary-button" disabled={busy} onClick={() => pay(intent)}>{busy ? 'Checking payment…' : 'Retry same request'}</button></div>}
    {recipient && draft ? <div className="payment-confirm" aria-label="Confirm simulated payment">
      <h4>Confirm your simulated payment</h4><p className="confirm-amount">₹{draft.amount}</p>
      <p><strong>{recipient.display_name}</strong><br />{recipient.upi_id}<br /><span>{recipient.bank_name}</span></p>
      {draft.note && <p>Note: {draft.note}</p>}
      <button className="primary-button" disabled={busy || intent !== null} onClick={() => pay({ key: crypto.randomUUID(), kind: 'transfer', payload: draft, uncertain: false })}>{busy ? 'Sending…' : `Confirm and send ₹${draft.amount}`}</button>
      <button className="text-button" disabled={busy || intent !== null} onClick={() => { setRecipient(null); setFeedback('') }}>Edit payment</button>
    </div> : !intent && <form aria-label="Send simulated money" onSubmit={review}>
      <h4>Send simulated money</h4><fieldset disabled={busy}>
        <label>Recipient UPI ID<input name="upi_id" required maxLength={48} placeholder="name-123abc@payflow" defaultValue={draft?.upi_id || ''} autoComplete="off" /></label>
        <div className="payment-fields"><label>Amount · INR<input name="amount" type="text" inputMode="decimal" required placeholder="0.00" defaultValue={draft?.amount || ''} /></label><label>Note · optional<input name="note" maxLength={140} placeholder="What’s it for?" defaultValue={draft?.note || ''} /></label></div>
        <button className="primary-button" type="submit">{busy ? 'Finding recipient…' : 'Review payment'}<span aria-hidden="true">↗</span></button>
      </fieldset>
    </form>}
    {receipt && <article className={`payment-receipt ${receipt.status.toLowerCase()}`} aria-label="Payment receipt">
      <div className="account-heading"><h4>Payment receipt</h4><span className="demo-tag">{receipt.status}</span></div>
      <p className="receipt-amount">₹{receipt.amount} <small>simulated INR</small></p>
      <p>{receipt.direction} · {receipt.counterparty_name}<br />{receipt.counterparty_upi_id}</p>
      <p className="receipt-id">Transaction ID<br />{receipt.transaction_id}</p>
      <p>{new Date(receipt.created_at).toLocaleString()}{receipt.note && <><br />{receipt.note}</>}</p>
      {receipt.failure_reason && <p>{receipt.failure_reason} · No funds moved.</p>}
    </article>}
    <section className="payment-history" aria-labelledby="history-title"><div className="account-heading"><h4 id="history-title">Payment history</h4><button className="text-button" disabled={historyLoading} onClick={refreshHistory}>Refresh history</button></div>
      {historyError && <p role="alert" className="feedback error">{historyError}</p>}
      {historyLoading && <p role="status" className="account-note">Loading payment history…</p>}
      {!historyLoading && !historyError && items.length === 0 && <p className="account-note">No payments yet. Add demo funds to get started.</p>}
      <ul className="history-list">{items.map((item) => <li key={item.transaction_id}><button disabled={busy} onClick={() => viewReceipt(item.transaction_id)} aria-label={`View receipt ${item.transaction_id}`}><span className="history-direction">{item.direction === 'INCOMING' ? '↙' : item.direction === 'OUTGOING' ? '↗' : '+'}</span><span className="history-copy"><strong>{item.counterparty_name}</strong><span>{item.direction} · {item.status}</span><span>{new Date(item.created_at).toLocaleString()}</span></span><span className="history-amount">{item.status === 'FAILED' ? '' : item.direction === 'OUTGOING' ? '−' : '+'}₹{item.amount}</span></button></li>)}</ul>
      {cursor && <button className="secondary-button" disabled={historyLoading} onClick={moreHistory}>Load older payments</button>}
    </section>
    <p className="account-note">Sandbox only. No real money, real banks, or actual UPI payments.</p>
  </section>
}
