import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, createAccount, getAccounts, getDemoBanks, setPrimaryAccount } from './api'
import type { BankAccount } from './api'
import PaymentPanel from './PaymentPanel'
import BankAccountCard from './BankAccountCard'
import type { DashboardView } from './navigation'
import { formatMoney } from './formatMoney'
import { minorUnits } from './moneyInput'

interface Props {
  token: string
  onLogout: (message?: string) => void
  view?: DashboardView | 'all'
  onNavigate?: (view: DashboardView) => void
}

export default function AccountPanel({ token, onLogout, view = 'all', onNavigate }: Props) {
  const [accounts, setAccounts] = useState<BankAccount[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [paymentsLocked, setPaymentsLocked] = useState(false)
  const account = accounts.find((item) => item.id === selectedId) || accounts.find((item) => item.is_primary) || accounts[0] || null
  const anchorId = accounts.length ? Math.min(...accounts.map((item) => item.id)) : 0
  const totalPaise = accounts.reduce((sum, item) => sum + minorUnits(item.balance), 0n)
  const totalBalance = `${totalPaise / 100n}.${String(totalPaise % 100n).padStart(2, '0')}`
  const [banks, setBanks] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [reload, setReload] = useState(0)
  const generation = useRef(0)
  const balanceRevision = useRef(0)

  useEffect(() => {
    let active = true
    const revision = balanceRevision.current
    Promise.all([getAccounts(token), getDemoBanks(token)])
      .then(([accounts, choices]) => {
        if (!active) return
        if (revision === balanceRevision.current) setAccounts(accounts)
        setBanks(choices)
      })
      .catch((failure: unknown) => {
        if (!active) return
        if (failure instanceof ApiError && failure.status === 401) {
          onLogout('Your session has expired. Please sign in again.')
        } else {
          setError(failure instanceof Error ? failure.message : 'Could not load your account.')
        }
      })
      .finally(() => { if (active) setLoading(false) })
      return () => { active = false; generation.current += 1 }
  }, [token, onLogout, reload])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (creating || paymentsLocked) return
    const bank = String(new FormData(event.currentTarget).get('bank_name') || '')
    if (!banks.includes(bank)) { setError('Choose a demo bank.'); return }
    const current = generation.current
    setCreating(true)
    setError('')
    setSuccess('')
    try {
      const created = await createAccount(token, bank)
      if (current !== generation.current) return
      setAccounts((old) => [...old, created])
      setSelectedId(created.id)
      setSuccess('Your simulated account and UPI ID are ready.')
    } catch (failure) {
      if (current !== generation.current) return
      if (failure instanceof ApiError && failure.status === 401) {
        onLogout('Your session has expired. Please sign in again.')
      } else {
        setError(failure instanceof Error ? failure.message : 'Could not create your account.')
      }
    } finally {
      if (current === generation.current) setCreating(false)
    }
  }

  function refresh() {
    balanceRevision.current += 1
    setLoading(true)
    setError('')
    setSuccess('')
    setReload((value) => value + 1)
  }

  async function refreshBalance() {
    const current = generation.current
    const revision = ++balanceRevision.current
    const accounts = await getAccounts(token)
    if (current === generation.current && revision === balanceRevision.current) setAccounts(accounts)
  }

  async function makePrimary(id: number) {
    if (paymentsLocked || creating) return
    const current = generation.current
    setCreating(true); setError('')
    try {
      await setPrimaryAccount(token, id)
      if (current !== generation.current) return
      await refreshBalance()
      if (current === generation.current) { setSelectedId(id); setSuccess('Primary account updated. Existing UPI destinations are unchanged.') }
    } catch (failure) {
      if (current === generation.current) {
        if (failure instanceof ApiError && failure.status === 401) onLogout('Your session has expired. Please sign in again.')
        else setError(failure instanceof Error ? failure.message : 'Could not change primary account.')
      }
    } finally { if (current === generation.current) setCreating(false) }
  }

  return (
    <section className="account-panel" aria-labelledby="accounts-title">
      <div className="account-overview" hidden={!!account && !['all', 'home', 'account', 'profile'].includes(view)}>
      <div className="account-heading">
        <h3 id="accounts-title">Your demo account</h3>
        <div className="account-controls">{onNavigate && (view === 'home' || view === 'profile') && <button type="button" className="text-button" onClick={() => onNavigate('account')}>Manage account</button>}<button type="button" className="text-button" disabled={loading || creating} onClick={refresh}>Refresh accounts</button></div>
      </div>
      {loading ? <p role="status" className="account-note">Loading your account…</p> : <>
        {error && <p role="alert" className="feedback error">{error} Use Refresh accounts to check the latest state.</p>}
        {success && <p role="status" className="feedback success">{success}</p>}
        {account ? (
          <div className="account-cards">{(view === 'account' ? accounts : [account]).map((item) => <BankAccountCard key={item.id} account={item} busy={creating || paymentsLocked} onPrimary={view === 'account' ? () => makePrimary(item.id) : undefined} />)}</div>
        ) : banks.length > 0 && (
          <div className="account-empty">
            <p className="empty-title">A fresh start for your payment sandbox.</p>
            <p className="account-note">No demo account yet. Choose a fictional bank to create one with ₹0.00 and your own @payflow ID.</p>
            <form aria-label="Create simulated bank account" onSubmit={submit}>
              <fieldset disabled={creating}>
                <label>Demo bank<select name="bank_name" required defaultValue=""><option value="" disabled>Choose a demo bank</option>{banks.map((bank) => <option key={bank} value={bank}>{bank}</option>)}</select></label>
                <button className="primary-button" type="submit">{creating ? 'Creating demo account…' : 'Create demo account'}<span aria-hidden="true">↗</span></button>
              </fieldset>
            </form>
            <p className="account-note">Up to four demo accounts. Funding allowance stays shared across your accounts.</p>
          </div>
        )}
      </>}
      </div>
      {account && view === 'home' && accounts.length > 1 && <p className="wallet-total">Total across your accounts · <strong>{formatMoney(totalBalance)}</strong> simulated INR</p>}
      {account && accounts.length > 1 && ['home', 'account', 'send', 'requests', 'splits', 'qr', 'all'].includes(view) && <label className="source-account-picker">Source account<select value={account.id} disabled={paymentsLocked || creating} onChange={(event) => setSelectedId(Number(event.target.value))}>{accounts.map((item) => <option key={item.id} value={item.id}>{item.bank_name} · {item.masked_account_number} · {formatMoney(item.balance)}{item.is_primary ? ' · Primary' : ''}</option>)}</select></label>}
      {account && view === 'account' && accounts.length < 4 && <form className="surface add-account" aria-label="Add simulated bank account" onSubmit={submit}><h4>Add a fictional account</h4><p className="account-note">Starts at zero. Your three funding actions remain user-wide.</p><fieldset disabled={creating || paymentsLocked}><label>Demo bank<select name="bank_name" required defaultValue=""><option value="" disabled>Choose a demo bank</option>{banks.map((bank) => <option key={bank}>{bank}</option>)}</select></label><button className="primary-button" type="submit">{creating ? 'Adding account…' : 'Add demo account'}</button></fieldset></form>}
      {account && <PaymentPanel key={anchorId} token={token} accountId={anchorId} sourceAccountId={account.id} accounts={accounts} onLockChanged={setPaymentsLocked} senderAccount={account} onLogout={onLogout} onBalanceChanged={refreshBalance} view={view} onNavigate={onNavigate} />}
    </section>
  )
}
