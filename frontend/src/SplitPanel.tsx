import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, resolveRecipient } from './api'
import type { BankAccount } from './api'
import { getContacts, getMoneyRequest } from './socialApi'
import type { MoneyRequest, PublicPerson, SavedContact } from './socialApi'
import { cancelSplit, createSplit, getSplit, getSplits, renewShare } from './splitApi'
import type { ExpenseSplit, SplitCreateInput, SplitPage, SplitScope } from './splitApi'
import { calculateShares } from './splitMath'
import { formatMoney } from './formatMoney'
import { minorUnits } from './moneyInput'
import type { DashboardView } from './navigation'
import ConfirmDialog from './ConfirmDialog'

interface Props {
  token: string
  accountId: number
  view: 'split-create' | 'splits'
  revision: number
  locked: boolean
  senderAccount: Pick<BankAccount, 'bank_name' | 'masked_account_number'>
  onNavigate?: (view: DashboardView) => void
  onLogout: (message?: string) => void
  onPay: (request: MoneyRequest) => Promise<void>
  onReceipt: (id: string) => Promise<void>
}
type Operation = { key: string; kind: 'create'; payload: SplitCreateInput } | { key: string; kind: 'renew'; splitId: string; participantId: string }
const storageKey = (id: number) => `payflow.split-operation.${id}`
function restore(id: number): Operation | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(storageKey(id)) || 'null')
    if (!value || !/^[0-9a-f-]{36}$/.test(value.key)) return null
    if (value.kind === 'create' && typeof value.payload?.title === 'string' && typeof value.payload?.total_amount === 'string' && Array.isArray(value.payload?.participants)) return value
    if (value.kind === 'renew' && typeof value.splitId === 'string' && typeof value.participantId === 'string') return value
  } catch { /* Server validation remains authoritative for untrusted browser metadata. */ }
  return null
}
function clearOperation(id: number, key: string) {
  try { if (JSON.parse(sessionStorage.getItem(storageKey(id)) || 'null')?.key === key) sessionStorage.removeItem(storageKey(id)) } catch { /* Replay remains safe. */ }
}

export default function SplitPanel({ token, accountId, view, revision, locked, senderAccount, onNavigate, onLogout, onPay, onReceipt }: Props) {
  const [contacts, setContacts] = useState<SavedContact[]>([])
  const [people, setPeople] = useState<PublicPerson[]>([])
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [total, setTotal] = useState('')
  const [includeCreator, setIncludeCreator] = useState(true)
  const [mode, setMode] = useState<'EQUAL' | 'CUSTOM'>('EQUAL')
  const [creatorCustom, setCreatorCustom] = useState('')
  const [custom, setCustom] = useState<Record<string, string>>({})
  const [acknowledged, setAcknowledged] = useState(false)
  const [draft, setDraft] = useState<SplitCreateInput | null>(null)
  const [page, setPage] = useState<SplitPage>({ items: [], next_cursor: null })
  const [scope, setScope] = useState<SplitScope>('all')
  const [selected, setSelected] = useState<ExpenseSplit | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [reload, setReload] = useState(0)
  const [pending, setPending] = useState<Operation | null>(() => restore(accountId))
  const [cancelling, setCancelling] = useState(false)
  const [payRequest, setPayRequest] = useState<MoneyRequest | null>(null)
  const [linked, setLinked] = useState<MoneyRequest | null>(null)
  const mounted = useRef(true)
  const posting = useRef(false)
  const disabled = locked || busy
  const selectedId = selected?.id

  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => {
    let active = true
    Promise.all([getContacts(token), getSplits(token, scope), selectedId ? getSplit(token, selectedId) : Promise.resolve(null)]).then(([saved, data, detail]) => {
      if (active) { setContacts(saved); setPage(data); if (detail) setSelected(detail) }
    }).catch((failure: unknown) => {
      if (!active) return
      if (failure instanceof ApiError && failure.status === 401) onLogout('Your session has expired. Please sign in again.')
      else setError(failure instanceof Error ? failure.message : 'Could not load splits.')
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [token, revision, reload, view, scope, selectedId, onLogout])

  function fail(failure: unknown) {
    if (failure instanceof ApiError && failure.status === 401) onLogout('Your session has expired. Please sign in again.')
    else setError(failure instanceof Error ? failure.message : 'Could not complete this split action.')
  }
  function refresh() { setLoading(true); setError(''); setReload((value) => value + 1) }
  function add(person: PublicPerson) {
    if (people.some((item) => item.upi_id === person.upi_id)) { setError('That participant is already included.'); return }
    if (people.length + Number(includeCreator) >= 10) { setError('A split supports at most ten people including yourself.'); return }
    setPeople((old) => [...old, person].sort((a, b) => a.upi_id.localeCompare(b.upi_id))); setDraft(null); setError('')
  }
  async function verify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (disabled || pending) return
    const upi = String(new FormData(event.currentTarget).get('upi') || '').trim().toLowerCase()
    setBusy(true); setError('')
    try { const person = await resolveRecipient(token, upi); if (mounted.current) add(person) }
    catch (failure) { if (mounted.current) fail(failure) }
    finally { if (mounted.current) setBusy(false) }
  }
  let preview: ReturnType<typeof calculateShares> | null = null
  let previewHint = 'Enter a total and choose participants to preview shares.'
  try { preview = calculateShares(total, people.map((person) => person.upi_id), includeCreator, mode, creatorCustom, custom) }
  catch (failure) { if (total && people.length) previewHint = failure instanceof Error ? failure.message : previewHint }
  function review(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (disabled || pending) return
    try {
      if (!title.trim() || !acknowledged) throw new Error('Enter a title and acknowledge the externally paid expense record.')
      const calculated = calculateShares(total, people.map((person) => person.upi_id), includeCreator, mode, creatorCustom, custom)
      setDraft({ title: title.trim(), description: description.trim(), total_amount: calculated.total, include_creator: includeCreator, mode,
        ...(mode === 'CUSTOM' && calculated.creator ? { creator_share: calculated.creator } : {}),
        participants: people.map((person) => ({ upi_id: person.upi_id, ...(mode === 'CUSTOM' ? { share_amount: calculated.shares[person.upi_id] } : {}) })) }); setError('')
    } catch (failure) { fail(failure) }
  }
  async function perform(next: Operation) {
    if (disabled || posting.current) return
    try { sessionStorage.setItem(storageKey(accountId), JSON.stringify(next)) }
    catch { setError('Enable session storage so this split action can be retried safely.'); return }
    posting.current = true; setBusy(true); setPending(next); setError('')
    try {
      const result = next.kind === 'create' ? await createSplit(token, next.key, next.payload) : await renewShare(token, next.splitId, next.participantId, next.key)
      clearOperation(accountId, next.key)
      if (!mounted.current) return
      setPending(null); setSelected(result); setDraft(null); setLinked(null)
      if (next.kind === 'create') { setTitle(''); setTotal(''); setDescription(''); setPeople([]); setCustom({}); setAcknowledged(false) }
      setSuccess(next.kind === 'create' ? 'Split created. No money moved.' : 'Unpaid contribution request renewed. The previous request cannot be paid.')
      refresh(); onNavigate?.('splits')
    } catch (failure) {
      if (mounted.current) {
        if (failure instanceof ApiError && failure.status >= 400 && failure.status < 500 && failure.status !== 408) { clearOperation(accountId, next.key); setPending(null); fail(failure) }
        else setError('Outcome unknown. Retry this exact split action with its saved key.')
      }
    } finally { posting.current = false; if (mounted.current) setBusy(false) }
  }
  async function open(id: string) {
    if (disabled) return
    setBusy(true); setError('')
    try { const data = await getSplit(token, id); if (mounted.current) { setSelected(data); setLinked(null) } }
    catch (failure) { if (mounted.current) fail(failure) }
    finally { if (mounted.current) setBusy(false) }
  }
  async function requestDetails(id: string, pay: boolean) {
    if (disabled || pending) return
    setBusy(true); setError('')
    try {
      const request = await getMoneyRequest(token, id)
      if (!mounted.current) return
      if (pay && request.status !== 'PENDING') throw new Error('The contribution is no longer pending. Refresh its split details.')
      if (pay) setPayRequest(request); else setLinked(request)
    } catch (failure) { if (mounted.current) fail(failure) }
    finally { if (mounted.current) setBusy(false) }
  }
  async function cancel() {
    if (!selected || disabled) return
    setCancelling(false); setBusy(true)
    try { const result = await cancelSplit(token, selected.id); if (mounted.current) { setSelected(result); setSuccess('Split cancelled. No payments were erased or refunded.'); refresh() } }
    catch (failure) { if (mounted.current) fail(failure) }
    finally { if (mounted.current) setBusy(false) }
  }
  async function more() {
    if (!page.next_cursor || disabled) return
    setBusy(true)
    try { const next = await getSplits(token, scope, page.next_cursor); if (mounted.current) setPage((old) => ({ ...next, items: [...old.items, ...next.items.filter((item) => !old.items.some((other) => other.id === item.id))] })) }
    catch (failure) { if (mounted.current) fail(failure) }
    finally { if (mounted.current) setBusy(false) }
  }

  return <section className="split-panel" aria-label="Split expenses">
    {error && <p className="feedback error" role="alert">{error}</p>}{success && <p className="feedback success" role="status">{success}</p>}
    {loading && <p role="status" className="account-note loading-indicator">Loading splits and saved contacts…</p>}
    {pending && <div className="uncertain-payment" role="alert"><strong>Keep this split action.</strong><p>{pending.kind === 'create' ? `Create ${pending.payload.title}` : 'Renew the same outstanding contribution'} · no money moves.</p><button className="secondary-button" disabled={disabled} onClick={() => perform(pending)}>Retry same split action</button></div>}
    {view === 'split-create' && <div className="surface">
      <h3>Create a split expense</h3><p className="account-note">Record an externally paid expense. PayFlow does not verify the original bill or debit your own share. Contributions are pinned to your primary account when created. Other people must explicitly pay their contributions.</p>
      {!draft ? <>
        <form aria-label="Verify split participant" onSubmit={verify}><fieldset disabled={disabled || pending !== null}><label>Participant UPI ID<input name="upi" maxLength={48} required placeholder="person@payflow" /></label><button className="secondary-button" type="submit">Verify and add participant</button></fieldset></form>
        <label>Add saved contact<select value="" disabled={disabled || pending !== null} onChange={(event) => { const contact = contacts.find((person) => person.upi_id === event.target.value); if (contact) add(contact) }}><option value="">Choose a saved contact</option>{contacts.map((contact) => <option key={contact.id} value={contact.upi_id}>{contact.display_name} · {contact.upi_id}</option>)}</select></label>
        <form aria-label="Create expense split" onSubmit={review}><fieldset disabled={disabled || pending !== null}>
          <label>Expense title<input maxLength={80} required value={title} onChange={(event) => setTitle(event.target.value)} /></label><label>Total expense · INR<input inputMode="decimal" required value={total} onChange={(event) => setTotal(event.target.value)} placeholder="0.00" /></label><label>Expense description · optional<input maxLength={240} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
          <label className="checkbox-label"><input type="checkbox" checked={includeCreator} onChange={(event) => setIncludeCreator(event.target.checked)} />Include my own share</label>
          <label>Split method<select value={mode} onChange={(event) => setMode(event.target.value as 'EQUAL' | 'CUSTOM')}><option value="EQUAL">Equal split</option><option value="CUSTOM">Custom split</option></select></label>
          <div className="share-preview" aria-label="Split share preview"><h4>Participant shares · preview</h4>{includeCreator && <div className="share-row"><span>You · external creator share</span>{mode === 'CUSTOM' ? <label>My custom share<input inputMode="decimal" value={creatorCustom} onChange={(event) => setCreatorCustom(event.target.value)} required /></label> : <strong>{preview?.creator ? formatMoney(preview.creator) : '—'}</strong>}</div>}{people.map((person) => <div className="share-row" key={person.upi_id}><span><strong>{person.display_name}</strong><small>{person.upi_id}</small></span>{mode === 'CUSTOM' ? <label>{`Share for ${person.display_name}`}<input inputMode="decimal" value={custom[person.upi_id] || ''} onChange={(event) => setCustom((old) => ({ ...old, [person.upi_id]: event.target.value }))} required /></label> : <strong>{preview ? formatMoney(preview.shares[person.upi_id]) : '—'}</strong>}<button className="text-button danger-text" type="button" aria-label={`Remove participant ${person.display_name}`} onClick={() => setPeople((old) => old.filter((item) => item.upi_id !== person.upi_id))}>Remove</button></div>)}{!preview && <p className="account-note">{previewHint}</p>}</div>
          <label className="checkbox-label"><input type="checkbox" required checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} />This is an externally paid expense record, not a verified PayFlow bill payment.</label><button className="primary-button" type="submit">Review split</button>
        </fieldset></form>
      </> : <div className="payment-confirm"><h4>Review expense split</h4><p><strong>{draft.title}</strong></p><p className="confirm-amount">{formatMoney(draft.total_amount)}</p><p>{draft.description}</p><p>{draft.participants.length + Number(draft.include_creator)} participants · {draft.mode.toLowerCase()} shares</p>{preview && <ul>{preview.creator && <li>Your external share: {formatMoney(preview.creator)}</li>}{people.map((person) => <li key={person.upi_id}>{person.display_name}: {formatMoney(preview!.shares[person.upi_id])}</li>)}</ul>}<p>No money moves now. Contributions become requests that expire after seven days. The server verifies every share.</p><button className="primary-button" disabled={disabled || pending !== null} onClick={() => perform({ key: crypto.randomUUID(), kind: 'create', payload: draft })}>Confirm and create split</button><button className="text-button" disabled={disabled || pending !== null} onClick={() => setDraft(null)}>Edit split</button></div>}
    </div>}
    {view === 'splits' && <>
      <div className="surface"><div className="account-heading"><h3>My splits</h3><button className="text-button" disabled={disabled} onClick={refresh}>Refresh splits</button></div><label>Show splits<select value={scope} disabled={disabled} onChange={(event) => { setScope(event.target.value as SplitScope); setSelected(null) }}><option value="all">All my splits</option><option value="created">Created by me</option><option value="shared">Shared with me</option><option value="settled">Settlement history</option></select></label>{!loading && !page.items.length && <p className="account-note">No splits here yet. Create a split or ask someone to include you.</p>}<ul className="split-list">{page.items.map((split) => <li key={split.id}><button disabled={disabled} onClick={() => open(split.id)}><span><strong>{split.title}</strong><small>{split.participant_count} people · {split.status} · {new Date(split.created_at).toLocaleDateString()}</small></span><span>{formatMoney(split.total_amount)}<small>Collected {formatMoney(split.contributions_received)} · Outstanding {formatMoney(split.outstanding_amount)}</small></span></button></li>)}</ul>{page.next_cursor && <button className="secondary-button" disabled={disabled} onClick={more}>Load older splits</button>}<button className="secondary-button" disabled={disabled || pending !== null} onClick={() => onNavigate?.('split-create')}>Create a new split</button></div>
      {selected && <section className="surface split-detail" aria-label="Split details"><div className="account-heading"><h3>{selected.title}</h3><span className="request-status">{selected.status}</span></div><p>{selected.description}</p><p className="account-note">Created by {selected.creator.display_name} · {selected.creator.upi_id}<br />{new Date(selected.created_at).toLocaleString()}<br />External expense record; original payment not verified by PayFlow.</p><dl className="split-totals"><div><dt>Total expense</dt><dd>{formatMoney(selected.total_amount)}</dd></div><div><dt>Creator's external share</dt><dd>{formatMoney(selected.creator_share)}</dd></div><div><dt>Contributions received</dt><dd>{formatMoney(selected.contributions_received)}</dd></div><div><dt>Uncollected contributions</dt><dd>{formatMoney(selected.outstanding_amount)}</dd></div></dl>{selected.status === 'CANCELLED' && <p className="account-note">Cancelled. Uncollected amounts are no longer actively requested.</p>}
        <ul className="requests-list">{selected.participants.map((part) => <li key={part.id} className="request-card"><div className="account-heading"><strong>{part.person.display_name}</strong><span className={`request-status status-${part.status.toLowerCase()}`}>{part.status === 'CREATOR_SHARE' ? 'CREATOR SHARE · EXTERNAL' : part.status}</span></div><p className="account-note">{part.person.upi_id}</p><p className="request-amount">{formatMoney(part.share_amount)}</p><div className="social-shortcuts">{part.can_pay && <button className="primary-button" disabled={disabled || pending !== null} onClick={() => requestDetails(part.request_id!, true)}>Pay my share</button>}{part.request_id && <button className="text-button" disabled={disabled} onClick={() => requestDetails(part.request_id!, false)}>Open linked request</button>}{part.payment_id && <button className="text-button" disabled={disabled} onClick={() => onReceipt(part.payment_id!)}>View share receipt</button>}{selected.is_creator && selected.status === 'OPEN' && ['DECLINED', 'CANCELLED', 'EXPIRED'].includes(part.status) && <button className="secondary-button" disabled={disabled || pending !== null} onClick={() => perform({ key: crypto.randomUUID(), kind: 'renew', splitId: selected.id, participantId: part.id })}>Renew unpaid request</button>}</div>{part.attempts.length > 0 && <details><summary>Settlement history</summary><ul>{part.attempts.map((attempt) => <li key={attempt.request_id}>{attempt.status} · {new Date(attempt.created_at).toLocaleString()}{attempt.payment_id && <span> · Receipt {attempt.payment_id}</span>}</li>)}</ul></details>}</li>)}</ul>
        {selected.is_creator && selected.status === 'OPEN' && minorUnits(selected.contributions_received) === 0n && <button className="secondary-button danger-text" disabled={disabled || pending !== null} onClick={() => setCancelling(true)}>Cancel unpaid split</button>}<button className="text-button" onClick={() => setSelected(null)}>Close split details</button>
      </section>}
      {linked && <section className="surface" aria-label="Linked money request"><h4>Linked payment request</h4><p>{linked.requester.display_name} requests {formatMoney(linked.amount)} from {linked.payer.display_name}</p><p>{linked.note} · {linked.status}</p><p className="account-note">Expires {new Date(linked.expires_at).toLocaleString()} · This is the same obligation shown in Requests.</p><button className="text-button" onClick={() => setLinked(null)}>Close linked request</button></section>}
    </>}
    {cancelling && <ConfirmDialog title="Cancel unpaid split?" action="Confirm split cancellation" busy={disabled} onClose={() => setCancelling(false)} onConfirm={cancel}><p>All still-pending contribution requests will close. A split with any paid contribution cannot be cancelled. No payments will be refunded or erased.</p></ConfirmDialog>}
    {payRequest && <ConfirmDialog title="Confirm split contribution" action="Confirm and pay share" busy={disabled} onClose={() => setPayRequest(null)} onConfirm={async () => { const request = payRequest; setPayRequest(null); await onPay(request) }}><p><strong>{payRequest.requester.display_name}</strong><br />{payRequest.requester.upi_id}</p><p className="request-amount">{formatMoney(payRequest.amount)}</p><p>{payRequest.note}</p><p>From {senderAccount.bank_name} · {senderAccount.masked_account_number}<br />Fictional funds only. This pays the same linked request, once.</p></ConfirmDialog>}
  </section>
}
