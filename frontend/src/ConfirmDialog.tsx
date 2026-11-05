import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'

export default function ConfirmDialog({ title, children, action, busy, actionDisabled = false, onConfirm, onClose }: { title: string; children: ReactNode; action: string; busy: boolean; actionDisabled?: boolean; onConfirm: () => void; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const element = dialog.current!
    const previous = document.activeElement as HTMLElement | null
    element.showModal()
    return () => { element.close(); if (previous?.isConnected) previous.focus() }
  }, [])
  return <dialog ref={dialog} className="qr-dialog confirm-dialog" aria-labelledby="confirmation-title" onCancel={(event) => { event.preventDefault(); if (!busy) onClose() }} onKeyDown={(event) => {
    if (event.key !== 'Tab' || event.ctrlKey || event.metaKey || event.altKey) return
    const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled)'))
    if (!controls.length) return
    const index = controls.indexOf(document.activeElement as HTMLElement)
    const next = event.shiftKey ? (index <= 0 ? controls.length - 1 : index - 1) : (index < 0 || index === controls.length - 1 ? 0 : index + 1)
    event.preventDefault()
    controls[next].focus()
  }}>
    <h3 id="confirmation-title">{title}</h3>
    {children}
    <div className="dialog-actions"><button className="secondary-button" disabled={busy} onClick={onClose} autoFocus>Go back</button><button className="primary-button" disabled={busy || actionDisabled} onClick={onConfirm}>{busy ? 'Working…' : action}</button></div>
  </dialog>
}
