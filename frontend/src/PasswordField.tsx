import { useState } from 'react'

export default function PasswordField({ confirmation = false, registering = false }: { confirmation?: boolean; registering?: boolean }) {
  const [visible, setVisible] = useState(false)
  const name = confirmation ? 'confirmation' : 'password'
  const label = confirmation ? 'Confirm password' : 'Password'
  return <div className="password-field">
    <label htmlFor={name}>{label}</label>
    <div className="password-input"><input id={name} name={name} type={visible ? 'text' : 'password'} autoComplete={registering ? 'new-password' : 'current-password'} required minLength={registering ? 8 : 1} maxLength={128} placeholder={confirmation ? 'Enter your password again' : registering ? 'Choose a strong password' : 'Enter your password'} /><button type="button" aria-label={`${visible ? 'Hide' : 'Show'} ${label.toLowerCase()}`} aria-pressed={visible} onClick={() => setVisible(!visible)}>{visible ? 'Hide' : 'Show'}</button></div>
  </div>
}
