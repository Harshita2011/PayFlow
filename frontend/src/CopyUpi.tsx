import { useState } from 'react'

export default function CopyUpi({ upiId }: { upiId: string }) {
  const [message, setMessage] = useState('')
  const [failed, setFailed] = useState(false)
  async function copy() {
    try {
      await navigator.clipboard.writeText(upiId)
      setFailed(false)
      setMessage('UPI ID copied.')
    } catch {
      setFailed(true)
      setMessage('Copy unavailable. Select and copy your UPI ID above.')
    }
  }
  return <div className="copy-upi"><button className="text-button" onClick={copy}>Copy UPI ID</button>{message && <span role="status" className={failed ? 'feedback error' : 'account-note'}>{message}</span>}</div>
}
