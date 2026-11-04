import { useState } from 'react'
import type { PaymentReceipt } from './api'
import { formatMoney } from './formatMoney'

interface Props {
  items: PaymentReceipt[]
  loading: boolean
  error: string
  busy: boolean
  cursor: string | null
  preview: boolean
  onRefresh: () => void
  onMore: () => void
  onReceipt: (id: string) => void
  onViewAll?: () => void
}

export default function PaymentHistory({ items, loading, error, busy, cursor, preview, onRefresh, onMore, onReceipt, onViewAll }: Props) {
  const [filter, setFilter] = useState('ALL')
  const filtered = items.filter((item) => filter === 'ALL' || item.direction === filter)
  const visible = preview ? items.slice(0, 3) : filtered
  return <section className="payment-history surface" aria-labelledby="history-title">
    <div className="account-heading"><div><h4 id="history-title">{preview ? 'Recent activity' : 'Payment history'}</h4><p className="account-note">Every movement of simulated money.</p></div><button className="text-button" disabled={loading} onClick={onRefresh}>Refresh history</button></div>
    {!preview && <label className="history-filter">Show transactions<select value={filter} onChange={(event) => setFilter(event.target.value)}><option value="ALL">All transactions</option><option value="INCOMING">Incoming transfers</option><option value="OUTGOING">Outgoing transfers</option><option value="FUNDING">Demo funding</option><option value="SELF">Self transfers</option></select></label>}
    {error && <p role="alert" className="feedback error">{error}</p>}
    {loading && <p role="status" className="account-note loading-indicator">Loading payment history…</p>}
    {!loading && !error && items.length === 0 && <div className="empty-state"><span aria-hidden="true">↗</span><p>No payments yet. Add demo funds to get started.</p></div>}
    {!loading && !error && items.length > 0 && visible.length === 0 && <p className="account-note">No matching transactions in the loaded history. Load older payments to see more.</p>}
    <ul className="history-list">{visible.map((item) => <li key={item.transaction_id}><button disabled={busy} onClick={() => onReceipt(item.transaction_id)} aria-label={`View receipt ${item.transaction_id}`}><span className={`history-direction ${item.direction.toLowerCase()}`}>{item.direction === 'SELF' ? '⇄' : item.direction === 'INCOMING' ? '↙' : item.direction === 'OUTGOING' ? '↗' : '+'}</span><span className="history-copy"><strong>{item.counterparty_name}</strong><span className={`status-${item.status.toLowerCase()}`}>{item.direction === 'SELF' ? 'SELF TRANSFER' : item.direction} · {item.status}</span><span>{new Date(item.created_at).toLocaleString()}</span>{item.type === 'SELF_TRANSFER' && <span>{item.source_bank} · {item.source_masked_account} → {item.destination_bank} · {item.destination_masked_account}</span>}</span><span className="history-amount">{item.status === 'FAILED' || item.direction === 'SELF' ? '' : item.direction === 'OUTGOING' ? '−' : '+'}{formatMoney(item.amount)}</span></button></li>)}</ul>
    {preview && onViewAll && <button className="text-button" onClick={onViewAll}>View all transactions →</button>}
    {!preview && cursor && <button className="secondary-button" disabled={loading} onClick={onMore}>Load older payments</button>}
    {!preview && <p className="account-note">Filters apply to loaded transactions. Load older payments for earlier results.</p>}
  </section>
}
