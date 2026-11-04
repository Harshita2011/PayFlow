import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, resolveRecipient } from './api'
import type { BankAccount, TransferInput } from './api'
import { addContact, closeMoneyRequest, createMoneyRequest, favoriteContact, getContacts, getMoneyRequest, getRecentContacts, getRequests, removeContact } from './socialApi'
import type { MoneyRequest, PublicPerson, RecentContact, RequestPage, SavedContact } from './socialApi'
import type { DashboardView } from './navigation'
import { canonicalAmount } from './moneyInput'
import { formatMoney } from './formatMoney'
import ConfirmDialog from './ConfirmDialog'

interface Props {
  token: string
  accountId: number
  view: DashboardView
  revision: number
  locked: boolean
  senderAccount: Pick<BankAccount, 'bank_name' | 'masked_account_number'>
  onNavigate?: (view: DashboardView) => void
  onLogout: (message?: string) => void
  onSend: (upi: string) => Promise<void>
  onPay: (request: MoneyRequest) => Promise<void>
  onReceipt: (id: string) => Promise<void>
}
type Creation = { key: string; payload: TransferInput }
type Confirmation = { kind: 'remove'; contact: SavedContact } | { kind: 'pay' | 'decline' | 'cancel'; item: MoneyRequest }
const emptyPage: RequestPage = { items: [], next_cursor: null, pending_count: 0 }
const creationKey = (id: number) => `payflow.collect-create.${id}`

function restoreCreation(id: number): Creation | null {
  try {
    const saved = JSON.parse(sessionStorage.getItem(creationKey(id)) || 'null')
    if (saved && /^[0-9a-f-]{36}$/.test(saved.key) && typeof saved.payload?.upi_id === 'string' && typeof saved.payload?.note === 'string') {
      canonicalAmount(saved.payload.amount)
      return saved
    }
  } catch { /* Browser metadata is untrusted; the backend validates every retry. */ }
  return null
}
function clearCreation(id: number, key: string) {
  try { if (JSON.parse(sessionStorage.getItem(creationKey(id)) || 'null')?.key === key) sessionStorage.removeItem(creationKey(id)) } catch { /* Same-key replay remains safe. */ }
}
function Initials({ person }: { person: PublicPerson }) {
  return <span className="contact-avatar" aria-hidden="true">{person.display_name.split(/\s+/).slice(0, 2).map((part) => part.charAt(0)).join('').toUpperCase()}</span>
}

export default function SocialPanel({ token, accountId, view, revision, locked, senderAccount, onNavigate, onLogout, onSend, onPay, onReceipt }: Props) {
  const [contacts, setContacts] = useState<SavedContact[]>([])
  const [recent, setRecent] = useState<RecentContact[]>([])
  const [incoming, setIncoming] = useState<RequestPage>(emptyPage)
  const [outgoing, setOutgoing] = useState<RequestPage>(emptyPage)
  const [tab, setTab] = useState<'incoming' | 'outgoing'>('incoming')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [reload, setReload] = useState(0)
  const [found, setFound] = useState<PublicPerson | null>(null)
  const [selected, setSelected] = useState<SavedContact | null>(null)
  const [draft, setDraft] = useState<TransferInput | null>(null)
  const [creation, setCreation] = useState<Creation | null>(() => restoreCreation(accountId))
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const mounted = useRef(true)
  const submitting = useRef(false)
  const disabled = busy || locked

  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 30000); return () => window.clearInterval(timer) }, [])
  useEffect(() => {
    let active = true
    Promise.all([getContacts(token), getRecentContacts(token), getRequests(token, 'incoming'), getRequests(token, 'outgoing')])
      .then(([saved, latest, received, sent]) => {
        if (!active) return
        setContacts(saved); setRecent(latest); setIncoming(received); setOutgoing(sent)
      }).catch((failure: unknown) => {
        if (!active) return
        if (failure instanceof ApiError && failure.status === 401) onLogout('Your session has expired. Please sign in again.')
        else setError(failure instanceof Error ? failure.message : 'Could not load contacts and requests.')
      }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [token, revision, reload, view, onLogout])

  function refresh() { setError(''); setLoading(true); setReload((value) => value + 1) }
  function fail(failure: unknown) {
    if (failure instanceof ApiError && failure.status === 401) onLogout('Your session has expired. Please sign in again.')
    else setError(failure instanceof Error ? failure.message : 'Could not complete this action.')
  }
  async function run(action: () => Promise<unknown>, message = '') {
    if (disabled || submitting.current) return
    submitting.current = true
    setBusy(true); setError(''); setSuccess('')
    try {
      await action()
      if (mounted.current) { setSuccess(message); refresh() }
    } catch (failure) { if (mounted.current) fail(failure) }
    finally { submitting.current = false; if (mounted.current) setBusy(false) }
  }
  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const upi = String(new FormData(event.currentTarget).get('upi') || '').trim().toLowerCase()
    await run(async () => {
      const person = await resolveRecipient(token, upi)
      if (mounted.current) { setFound(person); setDraft(null) }
    })
  }
  function requestFrom(person: PublicPerson) {
    setFound(person); setDraft(null); setError(''); setSuccess(''); onNavigate?.('request')
  }
  function reviewRequest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!found || disabled || creation) return
    const fields = new FormData(event.currentTarget)
    try { setDraft({ upi_id: found.upi_id, amount: canonicalAmount(String(fields.get('amount') || '').trim()), note: String(fields.get('note') || '').trim() }); setError('') }
    catch (failure) { fail(failure) }
  }
  async function sendRequest(next: Creation) {
    if (disabled || submitting.current) return
    try { sessionStorage.setItem(creationKey(accountId), JSON.stringify(next)) }
    catch { setError('Enable session storage so a request can be retried safely.'); return }
    submitting.current = true
    setBusy(true); setError(''); setCreation(next)
    try {
      await createMoneyRequest(token, next.key, next.payload)
      clearCreation(accountId, next.key)
      if (mounted.current) {
        setCreation(null); setDraft(null); setFound(null); setSuccess('Request sent. No money moved.'); setTab('outgoing'); refresh(); onNavigate?.('requests')
      }
    } catch (failure) {
      if (mounted.current) {
        if (failure instanceof ApiError && failure.status >= 400 && failure.status < 500 && failure.status !== 408) { clearCreation(accountId, next.key); setCreation(null); fail(failure) }
        else setError('Request creation outcome unknown. Retry with the saved key to avoid creating a duplicate.')
      }
    } finally { submitting.current = false; if (mounted.current) setBusy(false) }
  }
  async function openPay(item: MoneyRequest) {
    await run(async () => {
      const current = await getMoneyRequest(token, item.id)
      if (current.status !== 'PENDING') throw new Error('This request is no longer pending. Refresh requests.')
      if (mounted.current) setConfirmation({ kind: 'pay', item: current })
    })
  }
  async function confirm() {
    if (!confirmation || disabled) return
    const next = confirmation
    setConfirmation(null)
    if (next.kind === 'pay') { await onPay(next.item); return }
    if (next.kind === 'remove') {
      await run(async () => { await removeContact(token, next.contact.id); if (mounted.current) setSelected(null) }, 'Contact removed from your address book.')
    } else if (next.kind === 'decline' || next.kind === 'cancel') {
      const action = next.kind
      await run(() => closeMoneyRequest(token, next.item.id, action), action === 'decline' ? 'Request declined. No money moved.' : 'Request cancelled. No money moved.')
    }
  }
  async function more() {
    const page = tab === 'incoming' ? incoming : outgoing
    if (!page.next_cursor || disabled) return
    setBusy(true)
    try {
      const data = await getRequests(token, tab, page.next_cursor)
      if (!mounted.current) return
      const update = (old: RequestPage) => ({ ...data, items: [...old.items, ...data.items.filter((item) => !old.items.some((other) => other.id === item.id))] })
      if (tab === 'incoming') setIncoming(update); else setOutgoing(update)
    } catch (failure) { if (mounted.current) fail(failure) }
    finally { if (mounted.current) setBusy(false) }
  }
  const page = tab === 'incoming' ? incoming : outgoing
  const show = ['home', 'contacts', 'request', 'requests'].includes(view)
  const activity = [...incoming.items, ...outgoing.items].sort((a, b) => b.updated_at.localeCompare(a.updated_at)).slice(0, 8)

  return <section className="social-panel" hidden={!show} aria-label="Contacts and money requests">
    <div className="account-heading"><div><h3>{view === 'home' ? 'People & requests' : view === 'contacts' ? 'Your personal address book' : view === 'request' ? 'Request simulated money' : 'Your money requests'}</h3><p className="account-note">Saved contacts are personal, not mutual friendships. Requests never move money automatically.</p></div><button className="text-button" disabled={disabled || loading} onClick={refresh}>Refresh contacts & requests</button></div>
    {loading && <p className="account-note loading-indicator" role="status">Loading contacts and requests…</p>}
    {error && <p className="feedback error" role="alert">{error}</p>}
    {success && <p className="feedback success" role="status">{success}</p>}
    {creation && <div className="uncertain-payment" role="alert"><strong>Keep this request creation.</strong><p>{formatMoney(creation.payload.amount)} requested from {creation.payload.upi_id}. No funds move when creating a request.</p><button className="secondary-button" disabled={disabled} onClick={() => sendRequest(creation)}>Retry same request creation</button></div>}
    {view === 'home' && <div className="social-shortcuts"><button className="secondary-button" onClick={() => { setTab('incoming'); onNavigate?.('requests') }}>{incoming.pending_count} pending incoming requests</button><button className="secondary-button" onClick={() => onNavigate?.('contacts')}>Saved contacts · {contacts.length}</button></div>}
    {(view === 'home' || view === 'contacts') && <section className="surface recent-contacts" aria-labelledby="recent-contacts-title"><h4 id="recent-contacts-title">Recent contacts</h4>{!loading && recent.length === 0 && <p className="account-note">People you pay or receive money from will appear here.</p>}<div className="contact-strip">{recent.map((person) => <button disabled={disabled} key={person.upi_id} onClick={() => onSend(person.upi_id)} aria-label={`Send money to ${person.display_name}`}><Initials person={person} /><strong>{person.display_name}</strong><span>{person.upi_id}</span></button>)}</div></section>}
    {(view === 'contacts' || view === 'request') && <div className="surface contact-search"><form aria-label="Find PayFlow user" onSubmit={search}><h4>Find a PayFlow user</h4><p className="account-note">Use an exact @payflow ID. There is no public user directory.</p><fieldset disabled={disabled || creation !== null}><label>UPI ID to find<input name="upi" required maxLength={48} placeholder="name-123abc@payflow" autoComplete="off" /></label><button type="submit" className="primary-button">{busy ? 'Finding user…' : 'Verify user'}</button></fieldset></form>
      {found && <div className="qr-verified"><Initials person={found} /><strong>Verified: {found.display_name}</strong><span>{found.upi_id}</span>{view === 'contacts' && <button className="secondary-button" disabled={disabled} onClick={() => run(() => addContact(token, found.upi_id), 'Contact saved to your personal address book.')}>Add to saved contacts</button>}</div>}
      {view === 'request' && contacts.length > 0 && !creation && <label>Or choose a saved contact<select disabled={disabled} value={found && contacts.some((contact) => contact.upi_id === found.upi_id) ? found.upi_id : ''} onChange={(event) => { const contact = contacts.find((person) => person.upi_id === event.target.value); if (contact) { setFound(contact); setDraft(null) } }}><option value="">Choose a saved contact</option>{contacts.map((contact) => <option key={contact.id} value={contact.upi_id}>{contact.display_name} · {contact.upi_id}</option>)}</select></label>}
      {view === 'request' && found && !creation && (draft ? <div className="payment-confirm"><h4>Review your money request</h4><p className="confirm-amount">{formatMoney(draft.amount)}</p><p>Request from <strong>{found.display_name}</strong><br />{found.upi_id}</p><p>{draft.note}</p><p>Expires in 7 days. They must explicitly confirm a payment. No funds move now.</p><button className="primary-button" disabled={disabled} onClick={() => sendRequest({ key: crypto.randomUUID(), payload: draft })}>Send money request</button><button className="text-button" disabled={disabled} onClick={() => setDraft(null)}>Edit request</button></div> : <form aria-label="Enter money request" onSubmit={reviewRequest}><fieldset disabled={disabled}><label>Requested amount · INR<input name="amount" inputMode="decimal" required placeholder="0.00" /></label><label>Request note · optional<input name="note" maxLength={140} /></label><button type="submit" className="primary-button">Review request</button></fieldset></form>)}
    </div>}
    {view === 'contacts' && <>
      {!loading && contacts.length === 0 && <p className="account-note">No saved contacts yet. Verify a UPI ID above to save someone.</p>}
      {[true, false].map((favorites) => <section className="surface" key={String(favorites)}><h4>{favorites ? 'Favorites' : 'Saved contacts'}</h4>{!loading && !contacts.some((contact) => contact.is_favorite === favorites) && <p className="account-note">{favorites ? 'Mark a saved contact as a favorite for easy access.' : 'Your other saved contacts will appear here.'}</p>}<ul className="contacts-list">{contacts.filter((contact) => contact.is_favorite === favorites).map((contact) => <li key={contact.id}><button className="contact-profile-button" aria-label={`Open contact ${contact.display_name}`} onClick={() => setSelected(contact)}><Initials person={contact} /><span><strong>{contact.display_name}</strong><small>{contact.upi_id}</small></span></button><button className="text-button" disabled={disabled} aria-label={`${contact.is_favorite ? 'Unfavorite' : 'Favorite'} ${contact.display_name}`} onClick={() => run(async () => { const updated = await favoriteContact(token, contact.id, !contact.is_favorite); if (mounted.current && selected?.id === contact.id) setSelected(updated) })}>{contact.is_favorite ? '★' : '☆'}</button></li>)}</ul></section>)}
      {selected && <section className="surface" aria-label="Contact profile"><Initials person={selected} /><h4>{selected.display_name}</h4><p className="qr-upi">{selected.upi_id}</p><p className="account-note">Saved only in your personal address book.</p><div className="social-shortcuts"><button className="primary-button" disabled={disabled} onClick={() => onSend(selected.upi_id)}>Send Money</button><button className="secondary-button" disabled={disabled || creation !== null} onClick={() => requestFrom(selected)}>Request Money</button><button className="text-button danger-text" disabled={disabled} onClick={() => setConfirmation({ kind: 'remove', contact: selected })}>Remove contact</button><button className="text-button" onClick={() => setSelected(null)}>Close contact profile</button></div></section>}
    </>}
    {view === 'requests' && <section className="surface" aria-label="Money request inbox"><div className="auth-tabs" aria-label="Request direction"><button aria-pressed={tab === 'incoming'} onClick={() => setTab('incoming')}>Incoming ({incoming.pending_count})</button><button aria-pressed={tab === 'outgoing'} onClick={() => setTab('outgoing')}>Outgoing ({outgoing.pending_count})</button></div>
      {!loading && page.items.length === 0 && <p className="account-note">No {tab} money requests yet.</p>}
      <ul className="requests-list">{page.items.map((item) => { const person = tab === 'incoming' ? item.requester : item.payer; const expired = Date.parse(item.expires_at) <= now; return <li key={item.id} className="request-card"><div className="account-heading"><div className="request-person"><Initials person={person} /><div><strong>{person.display_name}</strong><p>{person.upi_id}</p></div></div><span className={`request-status status-${item.status.toLowerCase()}`}>{item.status === 'PENDING' && expired ? 'EXPIRED' : item.status}</span></div><p className="request-amount">{formatMoney(item.amount)} <small>simulated INR</small></p>{item.note && <p>{item.note}</p>}<p className="account-note">Created {new Date(item.created_at).toLocaleString()}<br />Expires {new Date(item.expires_at).toLocaleString()}</p><div className="social-shortcuts">{item.status === 'PENDING' && !expired && (tab === 'incoming' ? <><button className="primary-button" disabled={disabled} onClick={() => openPay(item)}>Pay request</button><button className="secondary-button" disabled={disabled} onClick={() => setConfirmation({ kind: 'decline', item })}>Decline request</button></> : <button className="secondary-button" disabled={disabled} onClick={() => setConfirmation({ kind: 'cancel', item })}>Cancel request</button>)}{item.payment_id && <button className="text-button" disabled={disabled} onClick={() => onReceipt(item.payment_id!)}>View payment receipt</button>}</div></li> })}</ul>
      {page.next_cursor && <button className="secondary-button" disabled={disabled} onClick={more}>Load older requests</button>}
      <details className="request-activity"><summary>Request activity</summary><p className="account-note">Derived from your loaded requests; no external notifications.</p><ul>{activity.map((item) => <li key={item.id}>{item.requester.display_name} requested {formatMoney(item.amount)} from {item.payer.display_name} · {item.status}</li>)}</ul></details>
    </section>}
    {confirmation && <ConfirmDialog title={confirmation.kind === 'remove' ? 'Remove saved contact?' : confirmation.kind === 'pay' ? 'Confirm request payment' : confirmation.kind === 'decline' ? 'Decline this request?' : 'Cancel this request?'} action={confirmation.kind === 'pay' ? 'Confirm and pay request' : confirmation.kind === 'remove' ? 'Remove contact' : confirmation.kind === 'decline' ? 'Confirm decline' : 'Confirm cancellation'} busy={disabled} onClose={() => setConfirmation(null)} onConfirm={confirm}>
      {confirmation.kind === 'remove' ? <p>Remove {confirmation.contact.display_name} from your address book? Their account and payment history are preserved.</p> : <><p><strong>{confirmation.item.requester.display_name}</strong><br />{confirmation.item.requester.upi_id}</p><p className="request-amount">{formatMoney(confirmation.item.amount)}</p><p>{confirmation.item.note}</p>{confirmation.kind === 'pay' && <p>From {senderAccount.bank_name} · {senderAccount.masked_account_number}<br />Simulated funds only. Confirming will submit this payment.</p>}</>}
    </ConfirmDialog>}
  </section>
}
