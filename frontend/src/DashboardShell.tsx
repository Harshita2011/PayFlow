import { useRef } from 'react'
import type { ReactNode } from 'react'
import type { User } from './api'
import { destinations } from './navigation'
import type { DashboardView } from './navigation'
import Icon from './Icon'

interface Props {
  user: User
  view: DashboardView
  onNavigate: (view: DashboardView) => void
  onLogout: () => void
  children: ReactNode
}

export default function DashboardShell({ user, view, onNavigate, onLogout, children }: Props) {
  const heading = useRef<HTMLHeadingElement>(null)
  const current = destinations.find((item) => item.id === view)!
  function navigate(next: DashboardView) {
    onNavigate(next)
    requestAnimationFrame(() => heading.current?.focus())
  }
  return <div className="dashboard-shell">
    <a className="skip-link" href="#dashboard-content">Skip to content</a>
    <aside className="sidebar">
      <button className="brand brand-button" onClick={() => navigate('home')} aria-label="PayFlow home"><span className="brand-mark">P↗</span>PayFlow<span className="brand-dot">.</span></button>
      <p className="nav-caption">YOUR WORKSPACE</p>
      <nav aria-label="Main navigation">{destinations.map((item) => <button key={item.id} data-secondary={!['home', 'send', 'scan', 'transactions', 'profile'].includes(item.id) ? true : undefined} aria-current={view === item.id ? 'page' : undefined} onClick={() => navigate(item.id)}><Icon name={item.icon} /><span>{item.label}</span></button>)}</nav>
      <div className="sidebar-note"><span className="simulation-badge">SIMULATION ONLY</span><p>A safe place to learn.<br />No real money moves here.</p></div>
      <button className="logout-button" onClick={onLogout}><Icon name="logout" />Log out</button>
    </aside>
    <div className="workspace">
      <header className="workspace-header"><span>Personal payment sandbox</span><button className="avatar-button" onClick={() => navigate('profile')} aria-label="Open profile"><span>{user.full_name.charAt(0).toUpperCase()}</span>{user.full_name.split(' ')[0]}</button></header>
      <main id="dashboard-content" tabIndex={-1}>
        <div className="page-heading"><div><p className="eyebrow">PAYFLOW / {current.label.toUpperCase()}</p><h1 ref={heading} tabIndex={-1}>{view === 'home' ? `Welcome, ${user.full_name.split(' ')[0]}.` : current.label}</h1><p>{current.description}</p></div><span className="simulation-badge">Demo funds · INR</span></div>
        {view === 'home' && <div className="quick-actions" aria-label="Quick actions">{destinations.filter((item) => ['send', 'scan', 'qr', 'transactions', 'request', 'contacts'].includes(item.id)).map((item) => <button key={item.id} onClick={() => navigate(item.id)}><span className="action-icon"><Icon name={item.icon} /></span>{item.label}<Icon name="arrow" /></button>)}</div>}
        {view === 'profile' && <div className="social-shortcuts"><button className="secondary-button" onClick={() => navigate('contacts')}>Saved Contacts</button><button className="secondary-button" onClick={() => navigate('requests')}>Money Requests</button><button className="secondary-button" onClick={() => navigate('request')}>Request Money</button></div>}
        {(view === 'home' || view === 'profile') && <div className="secondary-actions" aria-label="More sandbox tools"><button className="secondary-button" onClick={() => navigate('split-create')}>Split Expenses</button><button className="secondary-button" onClick={() => navigate('splits')}>My Splits</button><button className="secondary-button" onClick={() => navigate('account')}>My Bank Accounts</button><button className="secondary-button" onClick={() => navigate('self')}>Transfer to Self</button></div>}
        {children}
      </main>
      <footer className="workspace-footer">PayFlow sandbox · Fictional accounts, simulated funds, real learning.</footer>
    </div>
  </div>
}
