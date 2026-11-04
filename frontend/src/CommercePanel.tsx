import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import type { BankAccount } from './api'
import { ApiError } from './api'
import { getOperators, getPlans, getBillers, getBill, getBills, getRecharges, getSavedBillers, lookupBill, saveBiller, removeBiller, lookupSaved } from './commerceApi'
import type { Operator, Plan, Biller, Bill, Recharge, SavedBiller, Purchase } from './commerceApi'
import { formatMoney } from './formatMoney'
import { minorUnits } from './moneyInput'
import ConfirmDialog from './ConfirmDialog'

interface Props { token: string; accounts: BankAccount[]; sourceAccountId?: number; locked: boolean; revision: number; onPay: (purchase: Purchase) => void; onReceipt: (id: string) => void; onLogout: (message?: string) => void }

export default function CommercePanel({ token, accounts, sourceAccountId, locked, revision, onPay, onReceipt, onLogout }: Props) {
  const [tab, setTab] = useState('recharge')
  const [operators, setOperators] = useState<Operator[]>([])
  const [plans, setPlans] = useState<Plan[]>([])
  const [billers, setBillers] = useState<Biller[]>([])
  const [operator, setOperator] = useState('')
  const [planId, setPlanId] = useState('')
  const [category, setCategory] = useState('Electricity')
  const [billerId, setBillerId] = useState('')
  const [reference, setReference] = useState('')
  const [mobile, setMobile] = useState('')
  const [source, setSource] = useState(sourceAccountId || accounts[0]?.id || 0)
  const [bill, setBill] = useState<Bill | null>(null)
  const [bills, setBills] = useState<Bill[]>([])
  const [recharges, setRecharges] = useState<Recharge[]>([])
  const [billCursor, setBillCursor] = useState<string | null>(null)
  const [rechargeCursor, setRechargeCursor] = useState<string | null>(null)
  const [saved, setSaved] = useState<SavedBiller[]>([])
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [plansLoading, setPlansLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [review, setReview] = useState<Purchase | null>(null)
  const [removal, setRemoval] = useState<SavedBiller | null>(null)
  const mounted = useRef(true)
  const operating = useRef(false)
  const repeatPlan = useRef<string | null>(null)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  function report(e: unknown) {
    if (e instanceof ApiError && e.status === 401) onLogout('Your session has expired. Please sign in again.')
    else setError(e instanceof Error ? e.message : 'Could not load simulated services.')
  }
  useEffect(() => {
    let active = true
    // The refresh follows an external payment result.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true)
    Promise.all([getOperators(token), getBillers(token), getBills(token), getRecharges(token), getSavedBillers(token), bill ? getBill(token, bill.id) : Promise.resolve(null)]).then(([ops, providers, billPage, rechargePage, savedItems, refreshedBill]) => {
      if (!active) return
      setOperators(ops); setBillers(providers); setBills(billPage.items); setRecharges(rechargePage.items); setSaved(savedItems)
      setBillCursor(billPage.next_cursor); setRechargeCursor(rechargePage.next_cursor)
      setOperator((current) => current || ops[0]?.id || '')
      setBill((current) => refreshedBill || (current ? billPage.items.find((item) => item.id === current.id) || current : null))
      setReview(null)
    }).catch((e: unknown) => { if (active) report(e) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
    // Session changes unmount this panel; revision follows the shared payment controller.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, revision])
  useEffect(() => {
    if (!operator) return
    let active = true
    // Clear stale prices before loading another operator.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPlansLoading(true); setPlans([]); setPlanId('')
    getPlans(token, operator).then((items) => { if (active) { setPlans(items); if (repeatPlan.current && items.some((item) => item.id === repeatPlan.current)) setPlanId(repeatPlan.current); repeatPlan.current = null } }).catch((e: unknown) => { if (active) report(e) }).finally(() => { if (active) setPlansLoading(false) })
    return () => { active = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, operator])
  async function act(work: () => Promise<void>) {
    if (operating.current || locked) return
    operating.current = true; setBusy(true); setError(''); setNotice('')
    try { await work() } catch (e) { if (mounted.current) report(e) }
    finally { operating.current = false; if (mounted.current) setBusy(false) }
  }
  const disabled = locked || busy || loading
  const selected = accounts.find((item) => item.id === source)
  const plan = plans.find((item) => item.id === planId)
  const mobilePattern = operators.find((item) => item.id === operator)?.mobile_pattern || '^[6-9][0-9]{9}$'
  function prepare(purchase: Purchase) {
    setError('')
    if (!selected) { setError('Choose an owned source account.'); return }
    if (minorUnits(purchase.amount) > minorUnits(selected.balance)) { setError(`Insufficient simulated funds. Available: ${formatMoney(selected.balance)}.`); return }
    setReview(purchase)
  }
  function reviewRecharge(event: FormEvent) {
    event.preventDefault()
    if (!plan || !new RegExp(mobilePattern).test(mobile)) { setError('Select a demo plan and a ten-digit mobile number matching the displayed demo format.'); return }
    prepare({ kind: 'recharge', recharge: { mobile, plan_id: plan.id, source_account_id: source }, source_account_id: source, amount: plan.price, label: `${operators.find((item) => item.id === operator)?.name} · ${plan.name} · ••••••${mobile.slice(-4)}` })
  }
  async function fetchBill(event: FormEvent) {
    event.preventDefault()
    await act(async () => { const found = await lookupBill(token, billerId, reference); if (mounted.current) { setBill(found); setBills((items) => [found, ...items.filter((item) => item.id !== found.id)]) } })
  }
  function startBill(item: Bill) { setBill(item); setTab('utility'); setReview(null) }
  function repeatRecharge(item: Recharge) {
    const nextOperator = operators.find((op) => op.name === item.operator)?.id || ''
    setTab('recharge'); setMobile('')
    if (nextOperator === operator) setPlanId(plans.some((plan) => plan.id === item.plan_id) ? item.plan_id : '')
    else { repeatPlan.current = item.plan_id; setOperator(nextOperator) }
    setNotice('Re-enter the demo number for a fresh review. Full numbers are not retained.')
  }
  const bankPicker = <label>Source demo bank account<select value={source} disabled={disabled || !!review} onChange={(e) => setSource(Number(e.target.value))}>{accounts.map((item) => <option key={item.id} value={item.id}>{item.bank_name} · {item.masked_account_number} · {formatMoney(item.balance)}</option>)}</select></label>
  return <section className="commerce-panel surface" aria-label="Bills and recharge">
    <h3>Bills &amp; Recharge</h3><p className="account-note">Fictional services and simulated INR only. No mobile service is activated and no real bill is paid.</p>
    <div className="secondary-actions" aria-label="Service navigation">{[['recharge', 'Mobile Recharge'], ['utility', 'Utility Bills'], ['saved', 'Saved Billers'], ['history', 'Service History']].map(([id, label]) => <button key={id} className="secondary-button" aria-pressed={tab === id} disabled={disabled || !!review} onClick={() => { setTab(id); setError(''); setNotice('') }}>{label}</button>)}</div>
    {loading && <p role="status">Loading fictional services…</p>}
    {error && <p className="feedback error" role="alert">{error}</p>}{notice && <p className="feedback success" role="status">{notice}</p>}
    {error && !loading && <button className="text-button" disabled={busy} onClick={() => act(async () => { const [b, r, s, o, providers] = await Promise.all([getBills(token), getRecharges(token), getSavedBillers(token), getOperators(token), getBillers(token)]); if (mounted.current) { setBills(b.items); setRecharges(r.items); setSaved(s); setOperators(o); setBillers(providers); setOperator((value) => value || o[0]?.id || '') } })}>Refresh services</button>}
    {review ? <div className="payment-confirm" aria-label="Review service payment"><h4>Review simulated {review.kind === 'recharge' ? 'recharge' : 'bill payment'}</h4><p>{review.label}</p><p className="confirm-amount">{formatMoney(review.amount)}</p><p>From {accounts.find((item) => item.id === review.source_account_id)?.bank_name} · {accounts.find((item) => item.id === review.source_account_id)?.masked_account_number}</p><p>No real telecom or utility service is provided.</p><button className="primary-button" disabled={disabled} onClick={() => onPay(review)}>Confirm simulated payment</button><button className="text-button" disabled={disabled} onClick={() => setReview(null)}>Edit service payment</button></div> : <>
    {tab === 'recharge' && <form aria-label="Mobile recharge form" onSubmit={reviewRecharge}><fieldset disabled={disabled}>
      <label>Demo mobile number<input value={mobile} onChange={(e) => setMobile(e.target.value)} inputMode="numeric" pattern={mobilePattern} maxLength={10} required autoComplete="off" placeholder="9876543210" /></label><p className="account-note">Ten digits starting with {(operators.find((item) => item.id === operator)?.mobile_prefixes || '6789').split('').join(', ')}. No live operator or ownership lookup.</p>
      <label>Fictional operator<select value={operator} onChange={(e) => setOperator(e.target.value)} required><option value="" disabled>Select an operator</option>{operators.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      {plansLoading && <p role="status">Loading demo plans…</p>}
      <div className="service-plan-grid" role="group" aria-label="Simulated prepaid plans">{plans.map((item) => <label className={`service-plan ${planId === item.id ? 'selected' : ''}`} key={item.id}><input type="radio" name="plan" value={item.id} checked={planId === item.id} onChange={() => setPlanId(item.id)} /><strong>{item.name} · {formatMoney(item.price)}</strong><span>{item.validity_days} days · simulated</span><small>{item.description}</small></label>)}</div>
      {bankPicker}<button className="primary-button" type="submit" disabled={disabled || !plan}>Review recharge</button>
    </fieldset></form>}
    {tab === 'utility' && <><div className="secondary-actions" aria-label="Bill categories">{['Electricity', 'Water', 'Gas', 'Broadband'].map((item) => <button className="secondary-button" key={item} disabled={disabled} aria-pressed={category === item} onClick={() => { setCategory(item); setBillerId(''); setBill(null) }}>{item}</button>)}</div>
      <form aria-label="Find demo bill" onSubmit={fetchBill}><fieldset disabled={disabled}><label>Fictional biller<select value={billerId} onChange={(e) => { setBillerId(e.target.value); setBill(null) }} required><option value="" disabled>Select a biller</option>{billers.filter((item) => item.category === category).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>Demo customer reference<input value={reference} onChange={(e) => { setReference(e.target.value); setBill(null) }} pattern="DEMO[0-9]{6}" maxLength={10} required placeholder="DEMO000001" autoComplete="off" /></label><p className="account-note">Use DEMO followed by six digits. The same reference has one stable bill each month.</p><button className="primary-button" type="submit">{busy ? 'Fetching bill…' : 'Fetch demo bill'}</button></fieldset></form>
      {bill && <article className="service-record" aria-label="Demo bill details"><h4>{bill.biller}</h4><p>{bill.masked_reference} · {bill.billing_period}</p><p>{formatMoney(bill.amount_due)} · <strong>{bill.status}</strong></p><p>Due {bill.due_date}</p>{bill.status === 'PAID' ? <button className="secondary-button" disabled={disabled} onClick={() => onReceipt(bill.receipt!.transaction_id)}>View bill receipt</button> : <>{bankPicker}<button className="primary-button" disabled={disabled} onClick={() => prepare({ kind: 'bill', billId: bill.id, source_account_id: source, amount: bill.amount_due, label: `${bill.biller} · ${bill.masked_reference} · ${bill.billing_period}` })}>Review bill payment</button></>}</article>}
      <form aria-label="Save demo biller" onSubmit={(event) => { event.preventDefault(); const nickname = String(new FormData(event.currentTarget).get('nickname') || ''); void act(async () => { await saveBiller(token, billerId, reference, nickname); const items = await getSavedBillers(token); if (mounted.current) { setSaved(items); setNotice('Demo biller saved.') } }) }}><fieldset disabled={disabled || !billerId || !/^DEMO[0-9]{6}$/.test(reference)}><label>Biller nickname · optional<input name="nickname" maxLength={40} /></label><button className="secondary-button">Save biller and reference</button></fieldset></form>
    </>}
    {tab === 'saved' && <><h4>Saved Billers</h4>{!loading && saved.length === 0 && <p>No saved billers yet. Save a demo reference from Utility Bills.</p>}{saved.map((item) => <article className="service-record" key={item.id}><h4>{item.nickname || item.biller}</h4><p>{item.biller} · {item.masked_reference}</p><button className="secondary-button" disabled={disabled} onClick={() => act(async () => { const found = await lookupSaved(token, item.id); if (mounted.current) startBill(found) })}>Fetch current demo bill</button><button className="text-button" disabled={disabled} onClick={() => setRemoval(item)}>Remove saved biller</button></article>)}</>}
    {tab === 'history' && <><h4>Recharge history</h4>{!loading && recharges.length === 0 && <p>No simulated recharges yet.</p>}{recharges.map((item) => <article className="service-record" key={item.id}><h4>{item.operator} · {item.plan_name}</h4><p>{item.masked_mobile} · {formatMoney(item.receipt.amount)} · {item.status}</p><p>{new Date(item.created_at).toLocaleString()}<br />From {item.receipt.source_bank} · {item.receipt.source_masked_account}</p><p className="receipt-id">{item.receipt.transaction_id}</p><button className="secondary-button" disabled={disabled} onClick={() => onReceipt(item.receipt.transaction_id)}>View recharge receipt</button><button className="text-button" disabled={disabled} onClick={() => repeatRecharge(item)}>Repeat recharge</button></article>)}{rechargeCursor && <button className="secondary-button" disabled={disabled} onClick={() => act(async () => { const page = await getRecharges(token, rechargeCursor); if (mounted.current) { setRecharges((items) => [...items, ...page.items]); setRechargeCursor(page.next_cursor) } })}>Older recharges</button>}
      <h4>Utility bills and payment history</h4>{!loading && bills.length === 0 && <p>No demo bills yet.</p>}{bills.map((item) => <article className="service-record" key={item.id}><h4>{item.biller} · {item.category}</h4><p>{item.masked_reference} · {item.billing_period} · {formatMoney(item.amount_due)}</p><p>{item.status} · Due {item.due_date}{item.paid_at && ` · Paid ${new Date(item.paid_at).toLocaleString()}`}</p>{item.receipt ? <button className="secondary-button" disabled={disabled} onClick={() => onReceipt(item.receipt!.transaction_id)}>View bill receipt</button> : <button className="secondary-button" disabled={disabled} onClick={() => startBill(item)}>Open unpaid bill</button>}</article>)}{billCursor && <button className="secondary-button" disabled={disabled} onClick={() => act(async () => { const page = await getBills(token, billCursor); if (mounted.current) { setBills((items) => [...items, ...page.items]); setBillCursor(page.next_cursor) } })}>Older bills</button>}
    </>}
    </>}
    {removal && <ConfirmDialog title="Remove saved biller?" busy={busy} onClose={() => setRemoval(null)} onConfirm={() => act(async () => { await removeBiller(token, removal.id); if (mounted.current) { setSaved((items) => items.filter((item) => item.id !== removal.id)); setRemoval(null) } })} action="Remove biller"><p>{removal.biller} · {removal.masked_reference}</p><p>Existing bills and payments remain in history.</p></ConfirmDialog>}
  </section>
}
