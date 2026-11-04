import type { BankAccount } from './api'
import CopyUpi from './CopyUpi'
import { formatMoney } from './formatMoney'

export default function BankAccountCard({ account, onPrimary, busy = false }: { account: BankAccount; onPrimary?: () => void; busy?: boolean }) {
  return <article className="bank-card" aria-label="Simulated bank account">
    <div className="bank-card-heading"><span>{account.bank_name}</span><span className="demo-tag">{account.is_primary ? 'PRIMARY · SIMULATED' : 'SIMULATED'}</span></div>
    <p className="balance-label">Demo balance · INR</p><p className="account-balance">{formatMoney(account.balance)}</p>
    <dl className="account-details"><div><dt>Account number</dt><dd>{account.masked_account_number}</dd></div><div><dt>UPI ID · PayFlow sandbox only</dt><dd>{account.upi_id}</dd></div></dl>
    <CopyUpi upiId={account.upi_id} />
    {onPrimary && !account.is_primary && <button className="secondary-button" disabled={busy} onClick={onPrimary}>Set as primary account</button>}
    <p className="bank-disclaimer">Fictional funds. No real bank or UPI connection. This UPI ID always receives into this account.</p>
  </article>
}
