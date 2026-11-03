import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import App from './App'
import type { BankAccount } from './api'

const user = { id: 7, full_name: 'Test Learner', email: 'learner@example.com', created_at: '2026-11-03T10:00:00Z' }
const token = { access_token: 'test-access-token', token_type: 'bearer', expires_in: 900 }
const password = 'My-learning-password!'
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json' },
})

function mockAuthFetch(fetchMock: (url: string, options?: RequestInit) => unknown, accounts: BankAccount[] = []) {
  // Keep existing auth tests focused on their auth requests; the dashboard also loads accounts.
  vi.stubGlobal('fetch', (url: string, options?: RequestInit) => {
    if (url.includes('/payments/history')) return Promise.resolve(json({ items: [], next_cursor: null }))
    if (url.endsWith('/accounts/banks')) return Promise.resolve(json(['Grove Demo Bank']))
    if (url.endsWith('/accounts') && options?.method !== 'POST') return Promise.resolve(json(accounts))
    return fetchMock(url, options)
  })
}

function fillLogin() {
  fireEvent.change(screen.getByLabelText('Email address'), { target: { value: user.email } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: password } })
}

async function signIn() {
  fillLogin()
  fireEvent.submit(screen.getByRole('form', { name: 'Sign in' }))
  await screen.findByRole('heading', { name: 'Welcome, Test.' })
}

describe('PayFlow authentication', () => {
  it('removes the bank account and UPI ID when logging out', async () => {
    const account = { id: 5, bank_name: 'Grove Demo Bank', masked_account_number: 'SIM •••• •••• •••• 1234', upi_id: 'test-123@payflow', balance: '0.00', created_at: user.created_at }
    mockAuthFetch(vi.fn().mockResolvedValueOnce(json(token)).mockResolvedValueOnce(json(user)), [account])
    render(<App />)
    await signIn()
    await screen.findByText(account.upi_id)
    fireEvent.click(screen.getByRole('button', { name: 'Log out' }))
    expect(screen.queryByText(account.upi_id)).toBeNull()
    expect(screen.queryByRole('article', { name: 'Simulated bank account' })).toBeNull()
  })
  it('registers, switches to login, loads the protected profile, then logs out', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(user, 201))
      .mockResolvedValueOnce(json(token))
      .mockResolvedValueOnce(json(user))
    mockAuthFetch(fetchMock)
    const storageSpy = vi.spyOn(Storage.prototype, 'setItem')
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }))
    fireEvent.change(screen.getByLabelText('Full name'), { target: { value: user.full_name } })
    fillLogin()
    fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: password } })
    fireEvent.submit(screen.getByRole('form', { name: 'Create account' }))
    await screen.findByText('Account created. Sign in to continue.')
    expect(screen.getByLabelText('Password').getAttribute('type')).toBe('password')
    await signIn()
    expect(screen.getByText(user.email)).toBeTruthy()
    expect(fetchMock.mock.calls[0][0]).toBe('http://localhost:8001/register')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      full_name: user.full_name, email: user.email, password,
    })
    expect(fetchMock.mock.calls[2][1].headers.Authorization).toBe(`Bearer ${token.access_token}`)
    expect(storageSpy).not.toHaveBeenCalled()
    expect(document.body.textContent).not.toContain(token.access_token)
    expect(document.body.textContent).not.toContain(password)
    fireEvent.click(screen.getByRole('button', { name: 'Log out' }))
    expect(screen.queryByText(user.email)).toBeNull()
    expect(screen.queryByRole('button', { name: 'Refresh profile' })).toBeNull()
    expect(screen.getByLabelText('Email address').getAttribute('value')).toBe('')
    expect(screen.getByText('You’ve signed out of this browser session.')).toBeTruthy()
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('validates confirmation before calling the backend', () => {
    const fetchMock = vi.fn()
    mockAuthFetch(fetchMock)
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }))
    fillLogin()
    fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: 'different-password' } })
    fireEvent.submit(screen.getByRole('form', { name: 'Create account' }))
    expect(screen.getByRole('alert').textContent).toBe('Passwords do not match.')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('shows duplicate-email errors without changing forms', async () => {
    mockAuthFetch(vi.fn().mockResolvedValue(json({ detail: 'Email already registered' }, 409)))
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }))
    fireEvent.change(screen.getByLabelText('Full name'), { target: { value: user.full_name } })
    fillLogin()
    fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: password } })
    fireEvent.submit(screen.getByRole('form', { name: 'Create account' }))
    expect((await screen.findByRole('alert')).textContent).toBe('Email already registered')
    expect(screen.getByLabelText('Full name')).toBeTruthy()
  })

  it('shows invalid credentials and never opens a profile', async () => {
    mockAuthFetch(vi.fn().mockResolvedValue(json({ detail: 'Invalid email or password' }, 401)))
    render(<App />)
    fillLogin()
    fireEvent.submit(screen.getByRole('form', { name: 'Sign in' }))
    expect((await screen.findByRole('alert')).textContent).toBe('Invalid email or password')
    expect(screen.queryByRole('button', { name: 'Log out' })).toBeNull()
  })

  it('handles network failure and reenables the form', async () => {
    mockAuthFetch(vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    render(<App />)
    fillLogin()
    fireEvent.submit(screen.getByRole('form', { name: 'Sign in' }))
    expect((await screen.findByRole('alert')).textContent).toContain('Could not reach PayFlow')
    await waitFor(() => expect((screen.getByLabelText('Password') as HTMLInputElement).disabled).toBe(false))
    expect((screen.getByLabelText('Password') as HTMLInputElement).closest('fieldset')?.disabled).toBe(false)
  })

  it('disables form fields and prevents repeated submissions while waiting', async () => {
    let resolve!: (value: Response) => void
    const fetchMock = vi.fn().mockImplementationOnce(() => new Promise<Response>((done) => { resolve = done }))
      .mockResolvedValueOnce(json(user))
    mockAuthFetch(fetchMock)
    render(<App />)
    fillLogin()
    const form = screen.getByRole('form', { name: 'Sign in' })
    fireEvent.submit(form)
    expect((screen.getByLabelText('Password') as HTMLInputElement).closest('fieldset')?.disabled).toBe(true)
    fireEvent.submit(form)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await act(async () => { resolve(json(token)) })
    await screen.findByRole('button', { name: 'Log out' })
  })

  it('clears authentication on expiry', async () => {
    mockAuthFetch(vi.fn().mockResolvedValueOnce(json({ ...token, expires_in: 1 })).mockResolvedValueOnce(json(user)))
    render(<App />)
    await signIn()
    await screen.findByText('Your session has expired. Please sign in again.', {}, { timeout: 2500 })
    expect(screen.queryByText(user.email)).toBeNull()
    expect(screen.queryByRole('button', { name: 'Log out' })).toBeNull()
  })

  it('clears authentication if the protected endpoint returns 401', async () => {
    mockAuthFetch(vi.fn().mockResolvedValueOnce(json(token)).mockResolvedValueOnce(json(user))
      .mockResolvedValueOnce(json({ detail: 'Invalid or expired access token' }, 401)))
    render(<App />)
    await signIn()
    fireEvent.click(screen.getByRole('button', { name: 'Refresh profile' }))
    await screen.findByText('Your session has expired. Please sign in again.')
    expect(screen.queryByText(user.email)).toBeNull()
  })

  it('cannot restore a profile from a request that finishes after logout', async () => {
    let resolve!: (value: Response) => void
    const fetchMock = vi.fn().mockResolvedValueOnce(json(token)).mockResolvedValueOnce(json(user))
      .mockImplementationOnce(() => new Promise<Response>((done) => { resolve = done }))
    mockAuthFetch(fetchMock)
    render(<App />)
    await signIn()
    fireEvent.click(screen.getByRole('button', { name: 'Refresh profile' }))
    fireEvent.click(screen.getByRole('button', { name: 'Log out' }))
    await act(async () => { resolve(json(user)) })
    expect(screen.queryByText(user.email)).toBeNull()
    expect(screen.queryByRole('button', { name: 'Log out' })).toBeNull()
  })

  it('does not retain authentication across remounts', async () => {
    mockAuthFetch(vi.fn().mockResolvedValueOnce(json(token)).mockResolvedValueOnce(json(user)))
    const view = render(<App />)
    await signIn()
    view.unmount()
    render(<App />)
    expect(screen.queryByRole('button', { name: 'Log out' })).toBeNull()
    expect(screen.getByRole('heading', { name: 'Welcome back.' })).toBeTruthy()
  })
})
