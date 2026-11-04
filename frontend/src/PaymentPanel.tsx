import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, fundDemo, getPaymentHistory, getPaymentReceipt, resolveRecipient, transferMoney, selfTransfer } from './api'
import type { PaymentReceipt, Recipient, TransferInput, SelfTransferInput } from './api'
import type { BankAccount } from './api'
import MyQrCode from './MyQrCode'
import QrScanner from './QrScanner'
import PaymentHistory from './PaymentHistory'
import { formatMoney } from './formatMoney'
import type { DashboardView } from './navigation'
import { canonicalAmount, minorUnits } from './moneyInput'
import { payMoneyRequest } from './socialApi'
import type { MoneyRequest } from './socialApi'
import SocialPanel from './SocialPanel'
import SelfTransferPanel from './SelfTransferPanel'
import SplitPanel from './SplitPanel'

interface Props {
  token: string
  accountId: number
  sourceAccountId?: number
  accounts?: BankAccount[]
  onLockChanged?: (locked: boolean) => void
  senderAccount?: Pick<BankAccount, 'bank_name' | 'masked_account_number' | 'upi_id' | 'balance'>
  onLogout: (message?: string) => void
  onBalanceChanged: () => Promise<void>
  view?: DashboardView | 'all'
  onNavigate?: (view: DashboardView) => void
}

type Intent = { key: string; kind: 'fund' | 'transfer' | 'request' | 'self'; fundAccountId?: number; selfPayload?: SelfTransferInput; requestId?: string; payload?: TransferInput; uncertain: boolean }

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
    if (value.kind === 'fund') return { key: value.key, kind: 'fund', fundAccountId: value.fundAccountId, uncertain: true }
    if (value.kind === 'self' && value.selfPayload && Number.isInteger(value.selfPayload.source_account_id) && Number.isInteger(value.selfPayload.destination_account_id) && typeof value.selfPayload.note === 'string') {
      canonicalAmount(value.selfPayload.amount)
      return { key: value.key, kind: 'self', selfPayload: value.selfPayload, uncertain: true }
    }
    if ((value.kind === 'transfer' || (value.kind === 'request' && typeof value.requestId === 'string' && /^[0-9a-f-]{36}$/.test(value.requestId))) && value.payload && typeof value.payload.upi_id === 'string' &&
        typeof value.payload.amount === 'string' && typeof value.payload.note === 'string') {
      canonicalAmount(value.payload.amount)
      return { key: value.key, kind: value.kind, requestId: value.requestId, payload: value.payload, uncertain: true }
    }
  } catch { /* Corrupt/unavailable browser storage is never trusted as an API authority. */ }
  return null
}

export default function PaymentPanel({ token, accountId, senderAccount, onLogout, onBalanceChanged, view = 'all', onNavigate, accounts = [], sourceAccountId, onLockChanged }: Props) {
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [feedbackTone, setFeedbackTone] = useState<'error' | 'success'>('error')
  const [recipient, setRecipient] = useState<Recipient | null>(null)
  const [draft, setDraft] = useState<TransferInput | null>(null)
  const [intent, setIntent] = useState<Intent | null>(() => restoredIntent(accountId))
  const [receipt, setReceipt] = useState<PaymentReceipt | null>(null)
  const [items, setItems] = useState<PaymentReceipt[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState('')
  const [reload, setReload] = useState(0)
  const [scannerOpen, setScannerOpen] = useState(false)
  const [qrRecipient, setQrRecipient] = useState<Recipient | null>(null)
  const [formRevision, setFormRevision] = useState(0)
  const mounted = useRef(true)
  const posting = useRef(false)
  const amountInput = useRef<HTMLInputElement>(null)
  const confirmationAccount = accounts.find((account) => account.id === draft?.source_account_id) || senderAccount
  const insufficientMessage = confirmationAccount ? `Insufficient simulated funds. Available balance: ${formatMoney(confirmationAccount.balance)}.` : ''
  const confirmationOverBalance = !!(confirmationAccount && draft?.amount && minorUnits(draft.amount) > minorUnits(confirmationAccount.balance))

  function checkBalance(amount: string, sourceId?: number) {
    // Exact minor units, never floating-point money. The backend checks again under locks.
    const source = accounts.find((account) => account.id === sourceId) || senderAccount
    if (source && minorUnits(amount) > minorUnits(source.balance)) throw new Error(`Insufficient simulated funds. Available balance: ${formatMoney(source.balance)}.`)
  }

  useEffect(() => { onLockChanged?.(busy || intent !== null || recipient !== null) }, [busy, intent, recipient, onLockChanged])

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
    setFeedbackTone('error')
    if (error instanceof ApiError && error.status === 401) onLogout('Your session has expired. Please sign in again.')
    else setFeedback(error instanceof Error ? error.message : 'Something went wrong. Please try again.')
  }

  async function selectQrRecipient(upiId: string, signal: AbortSignal) {
    try {
      const found = await resolveRecipient(token, upiId)
      if (!mounted.current || signal.aborted) return
      setQrRecipient(found)
      setDraft({ upi_id: found.upi_id, amount: '', note: '' })
      setRecipient(null)
      setFeedback('')
      setFormRevision((value) => value + 1)
      onNavigate?.('send')
      requestAnimationFrame(() => amountInput.current?.focus())
    } catch (error) {
      if (!signal.aborted && mounted.current && error instanceof ApiError && error.status === 401) {
        onLogout('Your session has expired. Please sign in again.')
      }
      throw error
    }
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
        ...(sourceAccountId ? { source_account_id: sourceAccountId } : {}),
      }
      checkBalance(payload.amount, payload.source_account_id)
      setBusy(true)
      const found = await resolveRecipient(token, payload.upi_id)
      if (!mounted.current) return
      setDraft(payload)
      setRecipient(found)
    } catch (error) {
      if (mounted.current) handleError(error)
    } finally { if (mounted.current) setBusy(false) }
  }

  async function verify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || intent) return
    const upiId = String(new FormData(event.currentTarget).get('upi_id') || '').trim().toLowerCase()
    setBusy(true)
    setFeedback('')
    try {
      const found = await resolveRecipient(token, upiId)
      if (!mounted.current) return
      setQrRecipient(found)
      setDraft({ upi_id: found.upi_id, amount: '', note: '' })
      setFormRevision((value) => value + 1)
      requestAnimationFrame(() => amountInput.current?.focus())
    } catch (error) { if (mounted.current) handleError(error) }
    finally { if (mounted.current) setBusy(false) }
  }

  async function pay(next: Intent) {
    if (posting.current) return
    // An uncertain retry must reach the backend with its original key even if
    // the first attempt already debited the now-lower displayed balance.
    if (next.kind !== 'fund' && !next.uncertain) {
      try {
        if (next.kind === 'self') {
          const source = accounts.find((account) => account.id === next.selfPayload!.source_account_id)
          if (!source || minorUnits(next.selfPayload!.amount) > minorUnits(source.balance)) throw new Error('Insufficient simulated funds in the selected source account.')
        } else checkBalance(next.payload!.amount, next.payload?.source_account_id)
      }
      catch (error) { handleError(error); return }
    }
    posting.current = true
    try {
      // Persist BEFORE sending. Only the scoped retry key/payload, never the JWT.
      sessionStorage.setItem(pendingKey(accountId), JSON.stringify(next))
    } catch {
      posting.current = false
      setFeedbackTone('error')
      setFeedback('Cannot save the retry key in this tab. Enable browser session storage before sending.')
      return
    }
    setBusy(true)
    setFeedback('')
    setIntent(next)
    let result: PaymentReceipt
    try {
      result = next.kind === 'fund' ? await fundDemo(token, next.key, next.fundAccountId) : next.kind === 'request' ? await payMoneyRequest(token, next.requestId!, next.key, next.payload?.source_account_id) : next.kind === 'self' ? await selfTransfer(token, next.key, next.selfPayload!) : await transferMoney(token, next.key, next.payload!)
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
          setFeedbackTone('error')
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
      setQrRecipient(null)
      setFormRevision((value) => value + 1)
      setFeedbackTone('success')
      setFeedback(next.kind === 'fund' ? 'Simulated funds added successfully.' : next.kind === 'self' ? 'Simulated self-transfer completed.' : 'Simulated payment completed.')
      refreshHistory()
      try { await onBalanceChanged() }
      catch { if (mounted.current) { setFeedbackTone('error'); setFeedback('Payment succeeded. Balance refresh failed; use Refresh accounts to check it.') } }
      if (next.kind === 'request') onNavigate?.('transactions')
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
    <h3 id="payments-title" className="sr-only">Your payment sandbox</h3>
    {senderAccount && (view === 'all' || view === 'qr') && <div className="qr-tools surface">
      <MyQrCode upiId={senderAccount.upi_id} initiallyOpen={view === 'qr'} />
      <div className="qr-actions"><button className="secondary-button" disabled={busy || intent !== null} onClick={() => setScannerOpen(true)}>Scan QR</button><button className="secondary-button" disabled={busy || intent !== null} onClick={() => setScannerOpen(true)}>Upload QR Image</button></div>
      <p className="account-note">PayFlow QR codes identify a recipient. You choose the amount and confirm every payment.</p>
    </div>}
    {(scannerOpen || view === 'scan') && senderAccount && !intent && <QrScanner ownUpiId={senderAccount.upi_id} onRecipient={selectQrRecipient} onClose={() => { setScannerOpen(false); if (view === 'scan') onNavigate?.('send') }} />}
    {['all', 'home', 'account'].includes(view) && <div className="demo-funding"><div className="funding-symbol" aria-hidden="true">＋</div><p>Add fictional test funds.<span>₹1,000 per action · 3 actions per user.</span>{senderAccount && <span>Into {senderAccount.bank_name} · {senderAccount.masked_account_number}</span>}</p><button className="secondary-button" disabled={busy || intent !== null} onClick={() => pay({ key: crypto.randomUUID(), kind: 'fund', fundAccountId: sourceAccountId, uncertain: false })}>Add ₹1,000 demo funds</button></div>}
    {feedback && <p className={`feedback ${feedbackTone}`} role="status">{feedback}</p>}
    {intent?.uncertain && <div className="uncertain-payment" role="alert"><strong>Keep this payment request.</strong><p>{intent.kind === 'fund' ? 'Demo funding · ₹1,000.00' : intent.kind === 'self' ? `${formatMoney(intent.selfPayload!.amount)} between your own accounts` : `${formatMoney(intent.payload!.amount)} to ${intent.payload?.upi_id}`}</p><button className="primary-button" disabled={busy} onClick={() => pay(intent)}>{busy ? 'Checking payment…' : 'Retry same request'}</button></div>}
    {view !== 'all' && senderAccount && <SocialPanel token={token} accountId={accountId} view={view} revision={reload} locked={busy || intent !== null} senderAccount={senderAccount} onNavigate={onNavigate} onLogout={onLogout} onSend={async (upi) => {
      if (busy || intent) return
      setBusy(true)
      try { await selectQrRecipient(upi, new AbortController().signal) }
      catch (error) { if (mounted.current) handleError(error) }
      finally { if (mounted.current) setBusy(false) }
    }} onPay={(item: MoneyRequest) => pay({ key: crypto.randomUUID(), kind: 'request', requestId: item.id, payload: { upi_id: item.requester.upi_id, amount: item.amount, note: item.note, ...(sourceAccountId ? { source_account_id: sourceAccountId } : {}) }, uncertain: false })} onReceipt={async (id) => { await viewReceipt(id); onNavigate?.('transactions') }} />}
    {view === 'self' && <SelfTransferPanel accounts={accounts} locked={busy || intent !== null} onPay={(payload) => pay({ key: crypto.randomUUID(), kind: 'self', selfPayload: payload, uncertain: false })} />}
    {(view === 'split-create' || view === 'splits') && senderAccount && <SplitPanel token={token} accountId={accountId} view={view} revision={reload} locked={busy || intent !== null} senderAccount={senderAccount} onNavigate={onNavigate} onLogout={onLogout} onPay={(item) => pay({ key: crypto.randomUUID(), kind: 'request', requestId: item.id, payload: { upi_id: item.requester.upi_id, amount: item.amount, note: item.note, ...(sourceAccountId ? { source_account_id: sourceAccountId } : {}) }, uncertain: false })} onReceipt={async (id) => { await viewReceipt(id); onNavigate?.('transactions') }} />}
    <div hidden={!['all', 'send'].includes(view)} className="transfer-surface surface">
    {view !== 'all' && <ol className="payment-steps" aria-label="Payment progress"><li aria-current={!qrRecipient && !recipient ? 'step' : undefined}>1 · Recipient</li><li aria-current={qrRecipient && !recipient ? 'step' : undefined}>2 · Amount</li><li aria-current={recipient ? 'step' : undefined}>3 · Confirm</li></ol>}
    {recipient && draft ? <div className="payment-confirm" aria-label="Confirm simulated payment">
      <h4>Confirm your simulated payment</h4><p className="confirm-amount">{formatMoney(draft.amount)}</p>
      <p><strong>{recipient.display_name}</strong><br />{recipient.upi_id}<br /><span>{recipient.bank_name}</span></p>
      {confirmationAccount && <p className="sender-details">From {confirmationAccount.bank_name} · {confirmationAccount.masked_account_number}</p>}
      {draft.note && <p>Note: {draft.note}</p>}
      {confirmationOverBalance && <p className="feedback error" role="alert">{insufficientMessage}</p>}
      <button className="primary-button" disabled={busy || intent !== null || confirmationOverBalance} onClick={() => pay({ key: crypto.randomUUID(), kind: 'transfer', payload: draft, uncertain: false })}>{busy ? 'Sending…' : `Confirm and send ${formatMoney(draft.amount)}`}</button>
      <button className="text-button" disabled={busy || intent !== null} onClick={() => { setRecipient(null); setFeedback('') }}>Edit payment</button>
    </div> : !intent && (view !== 'all' && !qrRecipient ? <form aria-label="Find payment recipient" onSubmit={verify}><h4>Who are you paying?</h4><p className="account-note">Enter their exact @payflow ID. We’ll verify who it belongs to.</p><fieldset disabled={busy}><label>Recipient UPI ID<input name="upi_id" required maxLength={48} placeholder="name-123abc@payflow" autoComplete="off" /></label><button className="primary-button" type="submit">{busy ? 'Finding recipient…' : 'Verify recipient'}<span aria-hidden="true">↗</span></button><button type="button" className="secondary-button" onClick={() => setScannerOpen(true)}>Scan or upload a QR instead</button></fieldset></form> : <form key={formRevision} aria-label="Send simulated money" onSubmit={review}>
      <h4>Send simulated money</h4><fieldset disabled={busy}>
        {qrRecipient && <div className="qr-verified" role="status"><strong>Verified recipient: {qrRecipient.display_name}</strong><span>{qrRecipient.bank_name}</span><button className="text-button" type="button" onClick={() => { setQrRecipient(null); setDraft(null); setFormRevision((value) => value + 1) }}>Use a different recipient</button></div>}
        <label>Recipient UPI ID<input name="upi_id" required maxLength={48} placeholder="name-123abc@payflow" defaultValue={draft?.upi_id || ''} readOnly={qrRecipient !== null} autoComplete="off" /></label>
        <div className="payment-fields"><label>Amount · INR<input ref={amountInput} name="amount" type="text" inputMode="decimal" required placeholder="0.00" defaultValue={draft?.amount || ''} /></label><label>Note · optional<input name="note" maxLength={140} placeholder="What’s it for?" defaultValue={draft?.note || ''} /></label></div>
        <button className="primary-button" type="submit">{busy ? 'Finding recipient…' : 'Review payment'}<span aria-hidden="true">↗</span></button>
      </fieldset>
    </form>)}
    </div>
    {receipt && <article hidden={!['all', 'home', 'send', 'transactions', 'self'].includes(view)} className={`payment-receipt ${receipt.status.toLowerCase()}`} aria-label="Payment receipt">
      <div className="account-heading"><h4>Payment receipt</h4><span className="demo-tag">{receipt.status}</span></div>
      <p className="receipt-amount">{formatMoney(receipt.amount)} <small>simulated INR</small></p>
      <p>{receipt.direction === 'SELF' ? 'Self Transfer' : receipt.direction} · {receipt.counterparty_name}<br />{receipt.counterparty_upi_id}</p>
      {receipt.type === 'SELF_TRANSFER' && <p>From {receipt.source_bank} · {receipt.source_masked_account}<br />To {receipt.destination_bank} · {receipt.destination_masked_account}<br />No change to your combined funds.</p>}
      <p className="receipt-id">Transaction ID<br />{receipt.transaction_id}</p>
      <p>{new Date(receipt.created_at).toLocaleString()}{receipt.note && <><br />{receipt.note}</>}</p>
      {receipt.failure_reason && <p>{receipt.failure_reason} · No funds moved.</p>}
    </article>}
    <div hidden={!['all', 'home', 'transactions'].includes(view)}><PaymentHistory items={items} loading={historyLoading} error={historyError} busy={busy} cursor={cursor} preview={view === 'home'} onRefresh={refreshHistory} onMore={moreHistory} onReceipt={viewReceipt} onViewAll={onNavigate ? () => onNavigate('transactions') : undefined} /></div>
    <p className="account-note">Sandbox only. No real money, real banks, or actual UPI payments.</p>
  </section>
}
