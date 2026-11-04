import { useState } from 'react'
import type { FormEvent } from 'react'
import { apiRequest, registerUser } from './api'
import { useAuth } from './useAuth'
import AccountPanel from './AccountPanel'
import DashboardShell from './DashboardShell'
import PasswordField from './PasswordField'
import type { DashboardView } from './navigation'
import './App.css'

type Feedback = { kind: 'success' | 'error'; text: string } | null

function App() {
  const auth = useAuth()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [backendStatus, setBackendStatus] = useState('Not checked')
  const [checkingBackend, setCheckingBackend] = useState(false)
  const [email, setEmail] = useState('')
  const [view, setView] = useState<DashboardView>('home')

  function showError(error: unknown) {
    setFeedback({ kind: 'error', text: error instanceof Error ? error.message : 'Please try again.' })
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    const form = event.currentTarget
    const fields = new FormData(form)
    const password = String(fields.get('password') || '')
    setFeedback(null)
    if (mode === 'register' && password !== fields.get('confirmation')) {
      setFeedback({ kind: 'error', text: 'Passwords do not match.' })
      return
    }
    if (mode === 'register' && !String(fields.get('full_name') || '').trim()) {
      setFeedback({ kind: 'error', text: 'Please enter your full name.' })
      return
    }
    setBusy(true)
    try {
      if (mode === 'register') {
        await registerUser(String(fields.get('full_name')).trim(), email.trim(), password)
        form.reset()
        setMode('login')
        setFeedback({ kind: 'success', text: 'Account created. Sign in to continue.' })
      } else {
        await auth.login(email.trim(), password)
        setView('home')
        form.reset()
      }
    } catch (error) {
      showError(error)
    } finally {
      setBusy(false)
    }
  }

  async function refreshProfile() {
    setBusy(true)
    setFeedback(null)
    try {
      if (await auth.refreshProfile()) {
        setFeedback({ kind: 'success', text: 'Profile is up to date.' })
      }
    } catch (error) {
      showError(error)
    } finally {
      setBusy(false)
    }
  }

  async function checkBackend() {
    setCheckingBackend(true)
    setBackendStatus('Checking…')
    try {
      const data = await apiRequest<{ status: string }>('/health')
      setBackendStatus(data.status)
    } catch {
      setBackendStatus('Connection failed')
    } finally {
      setCheckingBackend(false)
    }
  }

  const user = auth.session?.user

  if (user && auth.session) return <DashboardShell user={user} view={view} onNavigate={setView} onLogout={() => { auth.logout(); setEmail(''); setFeedback({ kind: 'success', text: 'You’ve signed out of this browser session.' }); setMode('login') }}>
    <section className="profile-card surface" hidden={view !== 'profile'} aria-labelledby="profile-title">
      <div className="profile-avatar" aria-hidden="true">{user.full_name.charAt(0).toUpperCase()}</div>
      <h2 id="profile-title">Your profile</h2><div className="signed-in-label">Authenticated session</div>
      <dl className="profile-details"><div><dt>Full name</dt><dd>{user.full_name}</dd></div><div><dt>Email address</dt><dd>{user.email}</dd></div><div><dt>User ID</dt><dd>#{user.id}</dd></div><div><dt>Member since</dt><dd>{new Date(user.created_at).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })}</dd></div></dl>
      {feedback && <p role={feedback.kind === 'error' ? 'alert' : 'status'} className={`feedback ${feedback.kind}`}>{feedback.text}</p>}
      <button className="secondary-button" onClick={refreshProfile} disabled={busy}>{busy ? 'Refreshing…' : 'Refresh profile'}</button>
      <p className="account-note">Your token stays in memory. Refreshing the page signs you out. This is a simulated application with no real banking connection.</p>
    </section>
    <AccountPanel key={auth.session.token} token={auth.session.token} onLogout={auth.logout} view={view} onNavigate={setView} />
  </DashboardShell>

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand" href="/" aria-label="PayFlow home"><span className="brand-mark">P<span>↗</span></span>PayFlow<span className="brand-dot">.</span></a>
        <span className="simulation-badge"><span /> Learning sandbox</span>
      </header>

      <main className="auth-layout">
        <section className="intro" aria-labelledby="intro-title">
          <div className="eyebrow"><span className="eyebrow-line" /> A LITTLE PRACTICE. A LOT OF POSSIBILITY.</div>
          <h1 id="intro-title">Your next step <br />starts with <br /><span>PayFlow.</span></h1>
          <p className="intro-description">A space to explore how payments work.<br />Build confidence, one simulated step at a time.</p>
          <div className="flow-visual" aria-hidden="true">
            <span className="flow-node">You</span><span className="flow-path"><i /><i /><i /></span><span className="flow-center">P↗</span><span className="flow-path"><i /><i /><i /></span><span className="flow-node">Possibility</span>
          </div>
          <div className="intro-note"><span>✳</span><p>Made for learning.<br /><strong>No real money. Just real progress.</strong></p></div>
        </section>

        <section className="auth-card" aria-labelledby="card-title">
          <div className="card-topline"><span className="small-label">YOUR PAYFLOW SPACE</span><span className="step-label">LET’S GET STARTED</span></div>
              <h2 id="card-title">{mode === 'login' ? 'Welcome back.' : 'Make yourself at home.'}</h2>
              <p className="card-description">{mode === 'login' ? 'Sign in and pick up where you left off.' : 'Create your account. Start exploring.'}</p>
              <div className="auth-tabs" aria-label="Choose authentication form">
                <button type="button" aria-pressed={mode === 'login'} disabled={busy} onClick={() => { setMode('login'); setFeedback(null) }}>Sign in</button>
                <button type="button" aria-pressed={mode === 'register'} disabled={busy} onClick={() => { setMode('register'); setFeedback(null) }}>Create account</button>
              </div>
              {auth.sessionMessage && <p role="status" className="feedback notice">{auth.sessionMessage}</p>}
              {feedback && <p role={feedback.kind === 'error' ? 'alert' : 'status'} className={`feedback ${feedback.kind}`}>{feedback.text}</p>}
              <form key={mode} onSubmit={submit} aria-label={mode === 'login' ? 'Sign in' : 'Create account'}>
                <fieldset disabled={busy}>
                  {mode === 'register' && <label>Full name<input name="full_name" autoComplete="name" placeholder="Your full name" required maxLength={100} /></label>}
                  <label>Email address<input name="email" type="email" autoComplete="email" placeholder="you@example.com" value={email} onChange={(event) => setEmail(event.target.value)} required maxLength={255} /></label>
                  <PasswordField registering={mode === 'register'} />
                  {mode === 'register' && <>
                    <p className="input-hint">Use 8–128 characters. A long, unique phrase works well.</p>
                    <PasswordField confirmation registering />
                  </>}
                  <button className="primary-button" type="submit">{busy ? (mode === 'login' ? 'Signing in…' : 'Creating account…') : (mode === 'login' ? 'Sign in to PayFlow' : 'Create your account')}<span aria-hidden="true">↗</span></button>
                </fieldset>
              </form>
              <p className="session-note"><span aria-hidden="true">◇</span> Your session stays in this tab. Refreshing signs you out.</p>

          <div className="card-footer"><span className="footer-symbol" aria-hidden="true">◎</span> A simulation built for curious minds.</div>
        </section>
      </main>

      <footer className="site-footer"><span>© {new Date().getFullYear()} PayFlow <span className="footer-divider">/</span> UPI payment simulation</span><div className="backend-check"><span role="status">Backend: {backendStatus}</span><button onClick={checkBackend} disabled={checkingBackend}>Check Backend <span aria-hidden="true">↗</span></button></div></footer>
    </div>
  )
}

export default App
