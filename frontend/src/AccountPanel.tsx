import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, createAccount, getAccounts, getDemoBanks } from './api'
import type { BankAccount } from './api'
import PaymentPanel from './PaymentPanel'

interface Props {
  token: string
  onLogout: (message?: string) => void
}

export default function AccountPanel({ token, onLogout }: Props) {
  const [account, setAccount] = useState<BankAccount | null>(null)
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
        if (revision === balanceRevision.current) setAccount(accounts[0] ?? null)
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
    if (creating) return
    const bank = String(new FormData(event.currentTarget).get('bank_name') || '')
    if (!banks.includes(bank)) { setError('Choose a demo bank.'); return }
    const current = generation.current
    setCreating(true)
    setError('')
    setSuccess('')
    try {
      const created = await createAccount(token, bank)
      if (current !== generation.current) return
      setAccount(created)
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
    if (current === generation.current && revision === balanceRevision.current) setAccount(accounts[0] ?? null)
  }

  return (
    <section className="account-panel" aria-labelledby="accounts-title">
      <div className="account-heading">
        <h3 id="accounts-title">Your demo account</h3>
        <button type="button" className="text-button" disabled={loading || creating} onClick={refresh}>Refresh accounts</button>
      </div>
      {loading ? <p role="status" className="account-note">Loading your account…</p> : <>
        {error && <p role="alert" className="feedback error">{error} Use Refresh accounts to check the latest state.</p>}
        {success && <p role="status" className="feedback success">{success}</p>}
        {account ? (
          <article className="bank-card" aria-label="Simulated bank account">
            <div className="bank-card-heading"><span>{account.bank_name}</span><span className="demo-tag">SIMULATED</span></div>
            <p className="balance-label">Demo balance · INR</p>
            {/* Keep the exact decimal string; do not convert it with Number/parseFloat. */}
            <p className="account-balance">₹{account.balance}</p>
            <dl className="account-details">
              <div><dt>Account number</dt><dd>{account.masked_account_number}</dd></div>
              <div><dt>UPI ID · PayFlow sandbox only</dt><dd>{account.upi_id}</dd></div>
            </dl>
            <p className="bank-disclaimer">Fictional funds. No real bank or UPI connection.</p>
          </article>
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
            <p className="account-note">One simulated account per person. Only fictional money is used.</p>
          </div>
        )}
      </>}
      {account && <PaymentPanel key={account.id} token={token} accountId={account.id} onLogout={onLogout} onBalanceChanged={refreshBalance} />}
    </section>
  )
}
