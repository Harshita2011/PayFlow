import { useState } from 'react'
import type { FormEvent } from 'react'
import type { BankAccount, SelfTransferInput } from './api'
import { canonicalAmount, minorUnits } from './moneyInput'
import { formatMoney } from './formatMoney'

export default function SelfTransferPanel({ accounts, locked, onPay }: { accounts: BankAccount[]; locked: boolean; onPay: (payload: SelfTransferInput) => Promise<void> }) {
  const [draft, setDraft] = useState<SelfTransferInput | null>(null)
  const [error, setError] = useState('')
  function review(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (locked) return
    const fields = new FormData(event.currentTarget)
    try {
      const source = Number(fields.get('source'))
      const destination = Number(fields.get('destination'))
      const from = accounts.find((account) => account.id === source)
      const to = accounts.find((account) => account.id === destination)
      if (!from || !to || source === destination) throw new Error('Choose two different accounts you own.')
      const amount = canonicalAmount(String(fields.get('amount') || '').trim())
      if (minorUnits(amount) > minorUnits(from.balance)) throw new Error(`Insufficient simulated funds. Available balance: ${formatMoney(from.balance)}.`)
      setDraft({ source_account_id: source, destination_account_id: destination, amount, note: String(fields.get('note') || '').trim() }); setError('')
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Check the transfer details.') }
  }
  const from = accounts.find((account) => account.id === draft?.source_account_id)
  const to = accounts.find((account) => account.id === draft?.destination_account_id)
  return <section className="surface self-transfer" aria-label="Transfer between your accounts">
    <h3>Transfer to self</h3><p className="account-note">Move fictional funds between your own accounts. Your combined balance stays the same.</p>
    {accounts.length < 2 ? <p className="account-note">Add a second demo bank account in My Bank Accounts to get started.</p> : draft && from && to ? <div className="payment-confirm"><h4>Review self transfer</h4><p className="confirm-amount">{formatMoney(draft.amount)}</p><p>From {from.bank_name}<br />{from.masked_account_number}</p><p>To {to.bank_name}<br />{to.masked_account_number}</p><p>{draft.note}</p><button className="primary-button" disabled={locked} onClick={async () => { const next = draft; setDraft(null); await onPay(next) }}>Confirm self transfer</button><button className="text-button" disabled={locked} onClick={() => setDraft(null)}>Edit self transfer</button></div> : <form aria-label="Enter self transfer" onSubmit={review}><fieldset disabled={locked}>
      <label>From bank account<select name="source" defaultValue={accounts.find((account) => account.is_primary)?.id || accounts[0]?.id} required>{accounts.map((account) => <option key={account.id} value={account.id}>{account.bank_name} · {account.masked_account_number} · {formatMoney(account.balance)}</option>)}</select></label>
      <label>To bank account<select name="destination" defaultValue="" required><option value="" disabled>Choose your destination account</option>{accounts.map((account) => <option key={account.id} value={account.id}>{account.bank_name} · {account.masked_account_number}</option>)}</select></label>
      <label>Self transfer amount · INR<input name="amount" inputMode="decimal" required placeholder="0.00" /></label><label>Self transfer note · optional<input name="note" maxLength={140} /></label>
      <button type="submit" className="primary-button">Review self transfer</button></fieldset></form>}
    {error && <p className="feedback error" role="alert">{error}</p>}
  </section>
}
